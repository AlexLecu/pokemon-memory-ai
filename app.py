from flask import Flask, render_template, request, jsonify
import random
import requests
from functools import lru_cache
from datetime import date

app = Flask(__name__)

# In-memory game storage
games = {}

# Shared HTTP session
session = requests.Session()
session.headers.update({"User-Agent": "AI-Memory-Game/1.0 (+https://localhost)"})


# ---------- AI DIFFICULTY PROFILES ----------
# epsilon = exploration rate (random move)
# memory_window = how many recent moves to consider when refreshing memory
DIFFICULTY_PROFILES = {
    "easy":   {"epsilon": 0.50, "memory_window": 6},
    "medium": {"epsilon": 0.20, "memory_window": 12},
    "hard":   {"epsilon": 0.05, "memory_window": 999},  # effectively "all"
}


# ---------- THEME HELPERS ----------

EMOJI_POOL = [
    "🐶","🐱","🦊","🐻","🐼","🐨","🐯","🦁","🐮","🐷","🐸","🐵",
    "🦄","🐔","🐧","🐦","🐤","🐙","🦋","🐞","🦖","🦕","🐢","🐍",
    "🍎","🍌","🍓","🍒","🍉","🍍","🥝","🥑","🌶️","🥕","🥐","🍕",
    "⚽","🏀","🏈","🎾","🎲","🎹","🎸","🎧","🎯","🚗","🚲","🚀",
    "🌞","🌙","⭐","☁️","🌈","❄️","🔥","💧","🌊","🌳","🌵","🌸"
]

FLAG_POOL = [
    "🇺🇸","🇬🇧","🇫🇷","🇩🇪","🇯🇵","🇨🇦","🇮🇹","🇪🇸","🇨🇳","🇧🇷",
    "🇷🇺","🇷🇴","🇸🇪","🇳🇴","🇫🇮","🇦🇺","🇳🇿","🇲🇽","🇮🇳","🇰🇷",
    "🇹🇷","🇵🇱","🇭🇺","🇵🇹","🇬🇷","🇳🇱","🇧🇪","🇨🇭","🇩🇰","🇿🇦"
]


@lru_cache(maxsize=200)
def get_pokemon_data(pokemon_id: int):
    """Cached Pokémon fetch with robust sprite fallback."""
    try:
        r = session.get(f"https://pokeapi.co/api/v2/pokemon/{pokemon_id}", timeout=3)
        r.raise_for_status()
        data = r.json()
        sprites = data.get("sprites", {})
        img = (
            sprites.get("other", {})
            .get("official-artwork", {})
            .get("front_default")
            or sprites.get("front_default")
            or f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pokemon_id}.png"
        )
        return {
            "id": pokemon_id,
            "name": data.get("name", f"pokemon-{pokemon_id}").capitalize(),
            "image": img,
        }
    except Exception:
        return {
            "id": pokemon_id,
            "name": f"Pokemon {pokemon_id}",
            "image": f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pokemon_id}.png",
        }


def get_pokemon_list(count=8, rng=None):
    """Fast Pokémon list (Gen 1) using provided RNG (for seeding)."""
    rng = rng or random
    pokemon_ids = rng.sample(range(1, 151), count)
    return [get_pokemon_data(pid) for pid in pokemon_ids]


def call_ollama(prompt: str):
    """Call local Ollama for AI responses; fallback if unavailable."""
    try:
        r = session.post(
            "http://localhost:11434/api/generate",
            json={"model": "llama3.2", "prompt": prompt, "stream": False},
            timeout=3,
        )
        r.raise_for_status()
        txt = r.json().get("response", "").strip()
        if txt:
            return txt
        raise RuntimeError("Empty Ollama response")
    except Exception as e:
        print(f"Ollama error: {e}")
        return random.choice([
            "Are you even trying? 😂",
            "My grandmother could do better...",
            "This is painful to watch.",
            "Maybe memory games aren't your thing?"
        ])


# ---------- GAME ----------

class MemoryGame:
    def __init__(self, game_id, difficulty='medium', theme='pokemon', seed=None,
                 time_attack=False, time_seconds=0):
        self.id = game_id
        self.difficulty = difficulty
        self.theme = theme
        self.seed = seed

        # Pairs by difficulty
        if difficulty == 'easy':
            self.pairs = 6
        elif difficulty == 'hard':
            self.pairs = 12
        else:
            self.pairs = 8

        # Time-attack
        self.time_attack = bool(time_attack)
        self.time_seconds = int(time_seconds) if time_attack else 0  # client drives countdown

        # Seeded RNG if provided
        rng = random.Random(seed) if seed is not None else random

        # Build card pairs by theme
        self.cards = []
        if theme == 'pokemon':
            items = get_pokemon_list(self.pairs, rng=rng)
            for i, it in enumerate(items):
                self.cards.append(self._make_card(i * 2, it['id'], it['name'], image=it['image']))
                self.cards.append(self._make_card(i * 2 + 1, it['id'], it['name'], image=it['image']))
        elif theme == 'emoji':
            pool = rng.sample(EMOJI_POOL, self.pairs)
            for i, emo in enumerate(pool):
                name = f"Emoji {emo}"
                pair_id = 10_000 + i
                self.cards.append(self._make_card(i * 2, pair_id, name, emoji=emo))
                self.cards.append(self._make_card(i * 2 + 1, pair_id, name, emoji=emo))
        else:  # flags
            pool = rng.sample(FLAG_POOL, self.pairs)
            for i, flag in enumerate(pool):
                name = f"Flag {flag}"
                pair_id = 20_000 + i
                self.cards.append(self._make_card(i * 2, pair_id, name, emoji=flag))
                self.cards.append(self._make_card(i * 2 + 1, pair_id, name, emoji=flag))

        rng.shuffle(self.cards)

        # Game state
        self.moves = 0
        self.matches = 0
        self.player_score = 0
        self.ai_score = 0
        self.current_flipped = []
        self.move_history = []
        self.commentary_history = []
        self.mistakes = []

        # AI & modes
        self.ai_mode = False
        self.ai_difficulty = 'medium'
        self.ai_profile = DIFFICULTY_PROFILES['medium']
        self.ai_memory = {}  # pair_key -> [card_ids seen]
        self.current_player = 'player'
        self.commentary_frequency = 3

        # Stats: combo streaks & accuracy
        self.player_attempts = 0
        self.ai_attempts = 0
        self.player_pairs = 0
        self.ai_pairs = 0
        self.player_streak = 0
        self.ai_streak = 0
        self.best_streak = 0

    def _make_card(self, cid, pair_key, name, image=None, emoji=None):
        return {
            'id': cid,
            'pair_key': pair_key,
            'name': name,
            'image': image,   # URL or None
            'emoji': emoji,   # string or None
            'flipped': False,
            'matched': False
        }

    def visible_cards(self):
        """Only reveal media for flipped/matched cards."""
        return [{
            'id': c['id'],
            'flipped': c['flipped'],
            'matched': c['matched'],
            'image': c['image'] if c['flipped'] or c['matched'] else None,
            'emoji': c['emoji'] if c['flipped'] or c['matched'] else None,
            'name': c['name'] if c['flipped'] or c['matched'] else None
        } for c in self.cards]

    def preview_cards(self):
        """Reveal everything for blindfold preview (client may ignore if unused)."""
        return [{
            'id': c['id'],
            'flipped': c['flipped'],
            'matched': c['matched'],
            'image': c['image'],
            'emoji': c['emoji'],
            'name': c['name']
        } for c in self.cards]

    def _stats_fragment(self):
        """Stats snippet to include in API responses."""
        pa = round((self.player_pairs / self.player_attempts) * 100, 1) if self.player_attempts else 0.0
        aa = round((self.ai_pairs / self.ai_attempts) * 100, 1) if self.ai_attempts else 0.0
        return {
            'player_accuracy': pa,
            'ai_accuracy': aa,
            'best_streak': self.best_streak
        }

    def flip_card(self, card_id, player='player'):
        """Flip a card and check for matches."""
        card = next((c for c in self.cards if c['id'] == card_id), None)
        if not card or card['matched'] or card['flipped']:
            return {'success': False, 'message': 'Invalid card'}

        card['flipped'] = True
        self.current_flipped.append(card)
        self.current_player = player

        # Record move
        self.move_history.append({
            'card_id': card_id,
            'pair_key': card['pair_key'],
            'name': card['name'],
            'move_number': len(self.move_history) + 1,
            'player': player
        })

        # Track AI memory
        mem = self.ai_memory.setdefault(card['pair_key'], [])
        if card_id not in mem:
            mem.append(card_id)

        # If two cards are face up, resolve
        if len(self.current_flipped) == 2:
            self.moves += 1
            if player == 'player':
                self.player_attempts += 1
            else:
                self.ai_attempts += 1

            card1, card2 = self.current_flipped

            if card1['pair_key'] == card2['pair_key']:
                # MATCH
                card1['matched'] = True
                card2['matched'] = True
                self.matches += 1

                if player == 'player':
                    self.player_pairs += 1
                    self.player_streak += 1
                    bonus = max(0, self.player_streak - 1)  # 0,1,2...
                    self.player_score += 1 + bonus
                else:
                    self.ai_pairs += 1
                    self.ai_streak += 1
                    bonus = max(0, self.ai_streak - 1)
                    self.ai_score += 1 + bonus

                self.best_streak = max(self.best_streak, self.player_streak, self.ai_streak)
                self.current_flipped = []

                commentary = ""
                if self.matches % self.commentary_frequency == 0 or self.matches == self.pairs:
                    commentary = self.get_match_commentary()
                    if commentary:
                        self.commentary_history.append({
                            'text': commentary, 'type': 'match', 'player': player, 'move': self.moves
                        })

                payload = {
                    'success': True,
                    'match': True,
                    'cards': [card1, card2],
                    'moves': self.moves,
                    'matches': self.matches,
                    'player_score': self.player_score,
                    'ai_score': self.ai_score,
                    'game_won': self.matches == self.pairs,
                    'commentary': commentary,
                    'player': player
                }
                payload.update(self._stats_fragment())
                return payload

            else:
                # MISS
                mistake = f"{card1['name']}-{card2['name']}"
                self.mistakes.append(mistake)
                if player == 'player':
                    self.player_streak = 0
                else:
                    self.ai_streak = 0

                commentary = ""
                if self.moves % self.commentary_frequency == 0:
                    commentary = self.get_miss_commentary()
                    if commentary:
                        self.commentary_history.append({
                            'text': commentary, 'type': 'miss', 'player': player, 'move': self.moves
                        })

                payload = {
                    'success': True,
                    'match': False,
                    'cards': [card1, card2],
                    'moves': self.moves,
                    'player_score': self.player_score,
                    'ai_score': self.ai_score,
                    'commentary': commentary,
                    'player': player
                }
                payload.update(self._stats_fragment())
                self.current_flipped = []
                return payload

        # First of the pair flipped
        return {
            'success': True,
            'card': card,
            'player': player,
            'player_score': self.player_score,
            'ai_score': self.ai_score
        }

    def reset_unmatched(self):
        """Turn all unmatched cards face-down."""
        for card in self.cards:
            if not card['matched']:
                card['flipped'] = False
        self.current_flipped = []

    def get_match_commentary(self):
        """AI commentary for a match."""
        optimal_moves = self.pairs
        efficiency = (optimal_moves / max(self.moves, 1)) * 100
        if self.matches == self.pairs:
            if self.moves <= optimal_moves + 3:
                prompt = f"Player won {self.pairs}-pair memory in {self.moves} moves (near optimal). Short grudging compliment (1 sentence)."
            else:
                prompt = f"Player won but took {self.moves} moves for {self.pairs} pairs. Gentle mock (1 sentence)."
        elif efficiency > 80:
            prompt = "Player doing very well. Short competitive response (1 sentence)."
        else:
            prompt = "Player made match but struggling. Playful jab (1 sentence)."
        return call_ollama(prompt)

    def get_miss_commentary(self):
        """AI commentary for a miss."""
        last_mistake = self.mistakes[-1] if self.mistakes else None
        repeated = self.mistakes.count(last_mistake) if last_mistake else 0
        if repeated >= 3:
            prompt = f"Player flipped same wrong pair {repeated} times. Funny roast (1 sentence)."
        elif self.moves >= self.pairs * 2:
            prompt = f"Player at {self.moves} moves for {self.pairs} pairs. Sarcastic comment (1 sentence)."
        else:
            prompt = "Player missed. Short sassy comment (1 sentence)."
        return call_ollama(prompt)

    def get_performance_roast(self):
        """Roast about overall performance."""
        optimal = self.pairs
        current = self.moves
        ratio = current / optimal if optimal > 0 else 1
        if ratio > 3:
            prompt = f"Player took {current} moves for {self.matches}/{self.pairs} pairs (should be ~{optimal}). Savage roast (1 sentence)."
        elif ratio > 2:
            prompt = f"Player at {current} moves, {self.matches}/{self.pairs} matched. Struggling. Roast (1 sentence)."
        else:
            prompt = f"Player doing well - {current} moves, {self.matches}/{self.pairs} pairs. Competitive response (1 sentence)."
        return call_ollama(prompt)

    def get_ai_move(self):
        """
        AI chooses a card to flip using a difficulty profile:
          - epsilon: exploration rate (random move)
          - memory_window: how far back we refresh memory from history
        Strategy priority:
          1) If mate of current face-up card is known -> choose it.
          2) If any complete known pair exists -> choose one of them.
          3) Prefer unknown positions (ids never seen) to gain information.
          4) Otherwise random available.
        """
        profile = getattr(self, "ai_profile", DIFFICULTY_PROFILES.get(self.ai_difficulty, DIFFICULTY_PROFILES["medium"]))
        epsilon = profile["epsilon"]
        window = profile["memory_window"]

        # Refresh memory from recent moves
        recent = self.move_history[-window:] if window < 999 else self.move_history
        for move in recent:
            pk = move['pair_key']; cid = move['card_id']
            self.ai_memory.setdefault(pk, [])
            if cid not in self.ai_memory[pk]:
                self.ai_memory[pk].append(cid)

        # Available = unmatched & face-down
        available = [c for c in self.cards if not c['matched'] and not c['flipped']]
        if not available:
            return None

        # Helper: known positions per pair, filtered to those still available
        known_positions = {}
        for pk, ids in self.ai_memory.items():
            avail_ids = [cid for cid in ids if any(c['id'] == cid and not c['matched'] and not c['flipped'] for c in self.cards)]
            if avail_ids:
                known_positions[pk] = avail_ids

        # 1) If one card is face-up now, try to pick its mate if known
        if self.current_flipped:
            first = self.current_flipped[0]
            pk = first['pair_key']
            if pk in known_positions:
                for cid in known_positions[pk]:
                    if cid != first['id']:
                        if any(c['id'] == cid for c in available):
                            return cid

        # 2) If any complete known pair exists (two available positions), take one
        for pk, ids in known_positions.items():
            ids_avail = [cid for cid in ids if any(c['id'] == cid for c in available)]
            if len(set(ids_avail)) >= 2:
                return ids_avail[0]

        # 3) Exploration vs exploitation with epsilon
        import random as _r
        if _r.random() < epsilon:
            return _r.choice(available)['id']

        # Prefer unknown positions (ids never seen)
        seen_ids = set(cid for id_list in self.ai_memory.values() for cid in id_list)
        unknown_positions = [c for c in available if c['id'] not in seen_ids]
        if unknown_positions:
            return _r.choice(unknown_positions)['id']

        # 4) Otherwise, pick any available (all known)
        return _r.choice(available)['id']


# ---------- ROUTES ----------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/game/new', methods=['POST'])
def new_game():
    data = request.json or {}
    game_id = str(random.randint(100000, 999999))
    difficulty = data.get('difficulty', 'medium')
    theme = data.get('theme', 'pokemon')
    ai_mode = data.get('ai_mode', False)
    ai_difficulty = data.get('ai_difficulty', 'medium')

    # Daily seed or explicit seed
    daily = data.get('daily', False)
    seed = data.get('seed')
    if daily and seed is None:
        seed = f"{date.today().isoformat()}-{difficulty}-{theme}"

    # Time-attack settings
    time_attack = bool(data.get('time_attack', False))
    time_seconds = int(data.get('time_seconds') or 0)

    game = MemoryGame(
        game_id, difficulty, theme=theme, seed=seed,
        time_attack=time_attack, time_seconds=time_seconds
    )
    game.ai_mode = ai_mode
    game.ai_difficulty = ai_difficulty
    game.ai_profile = DIFFICULTY_PROFILES.get(ai_difficulty, DIFFICULTY_PROFILES["medium"])
    games[game_id] = game

    resp = {
        'game_id': game_id,
        'cards': game.visible_cards(),
        'preview_cards': game.preview_cards(),  # client may ignore
        'pairs': game.pairs,
        'theme': theme,
        'ai_mode': ai_mode,
        'ai_difficulty': ai_difficulty,
        'player_score': game.player_score,
        'ai_score': game.ai_score,
        'player_accuracy': 0.0,
        'ai_accuracy': 0.0,
        'best_streak': 0,
        'seed': seed,
        'daily': daily,
        'time_attack': game.time_attack,
        'time_seconds': game.time_seconds
    }
    return jsonify(resp)


@app.route('/api/game/<game_id>/flip', methods=['POST'])
def flip_card(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404

    game = games[game_id]
    data = request.json or {}
    card_id = data.get('card_id')
    player = data.get('player', 'player')

    result = game.flip_card(card_id, player)
    result['cards_state'] = game.visible_cards()
    result['commentary_history'] = game.commentary_history[-5:]
    return jsonify(result)


@app.route('/api/game/<game_id>/reset', methods=['POST'])
def reset_cards(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    game.reset_unmatched()
    return jsonify({'cards': game.visible_cards()})


@app.route('/api/game/<game_id>/time-bonus', methods=['POST'])
def apply_time_bonus(game_id):
    """Apply a small time bonus to player's score (1 point per 10s left)."""
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    data = request.json or {}
    seconds_left = max(0, int(data.get('seconds_left', 0)))
    bonus = seconds_left // 10
    game.player_score += bonus
    return jsonify({'bonus': bonus, 'player_score': game.player_score})


@app.route('/api/game/<game_id>/roast', methods=['GET'])
def get_roast(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    roast = game.get_performance_roast()
    return jsonify({'roast': roast})


@app.route('/api/game/<game_id>/ai-move', methods=['GET'])
def ai_move(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    card_id = game.get_ai_move()
    if card_id is None:
        return jsonify({'error': 'No valid moves'}), 400
    return jsonify({'card_id': card_id})


@app.route('/api/game/<game_id>/history', methods=['GET'])
def get_history(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    return jsonify({
        'move_history': game.move_history[-20:],
        'commentary_history': game.commentary_history
    })


@app.route('/api/game/<game_id>/ai-memory', methods=['GET'])
def ai_memory(game_id):
    """Expose a tiny view of AI's memory for the HUD."""
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    memory = []
    for pk, ids in game.ai_memory.items():
        name = next((c['name'] for c in game.cards if c['pair_key'] == pk), f"#{pk}")
        # count only currently known unique ids
        memory.append({"pair_key": pk, "name": name, "seen": len(set(ids))})
    memory.sort(key=lambda x: -x["seen"])
    return jsonify({"memory": memory[:8]})


if __name__ == '__main__':
    print("=" * 50)
    print("🎮 AI Memory Game with Roast Judge")
    print("=" * 50)
    print("⚠️  Ollama optional (for roasts):")
    print("   ollama pull llama3.2")
    print("   ollama serve")
    print("=" * 50)
    print("🌐 Open: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
