from flask import Flask, render_template, request, jsonify
import random
import requests
from functools import lru_cache
from datetime import date
import uuid

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
                 time_attack=False, time_seconds=0, mode='solo', opponent_difficulty='medium'):
        self.id = game_id
        self.difficulty = difficulty
        self.theme = theme
        self.seed = seed

        # Mode: 'solo', 'vs_ai', 'vs_human'
        if mode == 'vs_ai':
            self.opponent_is_ai = True
            self.vs_human = False
        elif mode == 'vs_human':
            self.opponent_is_ai = False
            self.vs_human = True
        else:
            mode = 'solo'
            self.opponent_is_ai = False
            self.vs_human = False
        self.mode = mode

        # Pairs by difficulty
        if difficulty == 'easy':
            self.pairs = 6
        elif difficulty == 'hard':
            self.pairs = 12
        else:
            self.pairs = 8

        # Time-attack (disabled for vs_human for simplicity)
        self.time_attack = bool(time_attack) and mode != 'vs_human'
        self.time_seconds = int(time_seconds) if self.time_attack else 0  # client drives countdown

        # Tokens and join status for multiplayer
        self.player1_token = str(uuid.uuid4()) if mode != 'solo' else None
        self.player2_token = None
        self.player2_joined = mode != 'vs_human'  # True for solo/vs_ai, False for vs_human initially

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
        self.player1_score = 0
        self.player2_score = 0
        self.current_flipped = []
        self.move_history = []
        self.commentary_history = []
        self.mistakes = []

        # Opponent settings (for vs_ai)
        self.opponent_difficulty = opponent_difficulty if self.opponent_is_ai else None
        self.opponent_profile = DIFFICULTY_PROFILES.get(opponent_difficulty, DIFFICULTY_PROFILES['medium']) if self.opponent_is_ai else None
        self.opponent_memory = {} if self.opponent_is_ai else None  # pair_key -> [card_ids seen]
        self.current_player = 'player1'
        self.commentary_frequency = 3

        # Stats: combo streaks & accuracy
        self.player1_attempts = 0
        self.player2_attempts = 0
        self.player1_pairs = 0
        self.player2_pairs = 0
        self.player1_streak = 0
        self.player2_streak = 0
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
        """Reveal everything for preview (client may ignore)."""
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
        pa1 = round((self.player1_pairs / self.player1_attempts) * 100, 1) if self.player1_attempts else 0.0
        pa2 = round((self.player2_pairs / self.player2_attempts) * 100, 1) if self.player2_attempts else 0.0
        return {
            'player1_accuracy': pa1,
            'player2_accuracy': pa2,
            'best_streak': self.best_streak
        }

    def flip_card(self, card_id, player='player1', token=None):
        """Flip a card and check for matches."""
        # Token validation
        if self.mode != 'solo':
            if self.opponent_is_ai and player == 'player2':
                pass  # No token needed for AI flips
            else:
                if token is None:
                    return {'success': False, 'message': 'Token required'}
                if player == 'player1' and token != self.player1_token:
                    return {'success': False, 'message': 'Invalid token'}
                if player == 'player2' and token != self.player2_token:
                    return {'success': False, 'message': 'Invalid token'}
        if self.mode == 'solo' and player != 'player1':
            return {'success': False, 'message': 'Invalid player'}

        if player != self.current_player:
            return {'success': False, 'message': 'Not your turn'}

        card = next((c for c in self.cards if c['id'] == card_id), None)
        if not card or card['matched'] or card['flipped']:
            return {'success': False, 'message': 'Invalid card'}

        card['flipped'] = True
        self.current_flipped.append(card)

        # Record move
        self.move_history.append({
            'card_id': card_id,
            'pair_key': card['pair_key'],
            'name': card['name'],
            'move_number': len(self.move_history) + 1,
            'player': player
        })

        # Track opponent memory if AI
        if self.opponent_is_ai:
            mem = self.opponent_memory.setdefault(card['pair_key'], [])
            if card_id not in mem:
                mem.append(card_id)

        # If two cards are face up, resolve
        if len(self.current_flipped) == 2:
            self.moves += 1
            if player == 'player1':
                self.player1_attempts += 1
            else:
                self.player2_attempts += 1

            card1, card2 = self.current_flipped

            if card1['pair_key'] == card2['pair_key']:
                # MATCH
                card1['matched'] = True
                card2['matched'] = True
                self.matches += 1

                if player == 'player1':
                    self.player1_pairs += 1
                    self.player1_streak += 1
                    bonus = max(0, self.player1_streak - 1)  # 0,1,2...
                    self.player1_score += 1 + bonus
                else:
                    self.player2_pairs += 1
                    self.player2_streak += 1
                    bonus = max(0, self.player2_streak - 1)
                    self.player2_score += 1 + bonus

                self.best_streak = max(self.best_streak, self.player1_streak, self.player2_streak)
                self.current_flipped = []

                # ALWAYS alternate after resolving a pair in non-solo modes
                if self.mode != 'solo':
                    self.current_player = 'player2' if player == 'player1' else 'player1'

                commentary = ""
                # FIX: endgame commentary respects actual winner in AI mode
                if self.matches == self.pairs:
                    commentary = self.get_endgame_commentary(player)
                elif self.matches % self.commentary_frequency == 0:
                    commentary = self.get_match_commentary(player)
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
                    'player1_score': self.player1_score,
                    'player2_score': self.player2_score,
                    'game_won': self.matches == self.pairs,
                    'commentary': commentary,
                    'player': player,
                    'current_player': self.current_player,  # include turn info
                }
                payload.update(self._stats_fragment())
                return payload

            else:
                # MISS
                mistake = f"{card1['name']}-{card2['name']}"
                self.mistakes.append(mistake)
                if player == 'player1':
                    self.player1_streak = 0
                else:
                    self.player2_streak = 0

                # Alternate to the other player in non-solo modes
                if self.mode != 'solo':
                    self.current_player = 'player2' if player == 'player1' else 'player1'

                commentary = ""
                if self.moves % self.commentary_frequency == 0:
                    commentary = self.get_miss_commentary(player)
                    if commentary:
                        self.commentary_history.append({
                            'text': commentary, 'type': 'miss', 'player': player, 'move': self.moves
                        })

                payload = {
                    'success': True,
                    'match': False,
                    'cards': [card1, card2],
                    'moves': self.moves,
                    'player1_score': self.player1_score,
                    'player2_score': self.player2_score,
                    'commentary': commentary,
                    'player': player,
                    'current_player': self.current_player,  # include turn info
                }
                payload.update(self._stats_fragment())
                self.current_flipped = []
                return payload

        # First of the pair flipped
        return {
            'success': True,
            'card': card,
            'player': player,
            'player1_score': self.player1_score,
            'player2_score': self.player2_score
        }

    def reset_unmatched(self):
        """Turn all unmatched cards face-down."""
        for card in self.cards:
            if not card['matched']:
                card['flipped'] = False
        self.current_flipped = []

    def get_player_name(self, player):
        if player == 'player1':
            return "Player 1"
        else:
            return "AI" if self.opponent_is_ai else "Player 2"

    def get_match_commentary(self, player):
        """AI commentary for a mid-game match (non-final)."""
        player_name = self.get_player_name(player)
        optimal_moves = self.pairs
        efficiency = (optimal_moves / max(self.moves, 1)) * 100
        if efficiency > 80:
            prompt = f"{player_name} doing very well. Short competitive response (1 sentence)."
        else:
            prompt = f"{player_name} made a match but still has room to improve. Playful jab (1 sentence)."
        return call_ollama(prompt)

    def get_endgame_commentary(self, player):
        """AI commentary when the board is cleared; respects actual winner."""
        p1 = self.player1_score
        p2 = self.player2_score
        if self.mode == 'solo':
            optimal_moves = self.pairs
            if self.moves <= optimal_moves + 3:
                prompt = f"Player won {self.pairs}-pair memory in {self.moves} moves (near optimal). Short grudging compliment (1 sentence)."
            else:
                prompt = f"Player won but took {self.moves} moves for {self.pairs} pairs. Gentle mock (1 sentence)."
        elif self.opponent_is_ai:
            if p1 > p2:
                prompt = f"Game over: Player beat the AI {p1} to {p2}. Brief congrats to the player (1 sentence)."
            elif p2 > p1:
                prompt = f"Game over: AI beat the player {p2} to {p1}. Short smug remark from the AI (1 sentence)."
            else:
                prompt = f"Game over: Tie at {p1} each. Short playful tie remark (1 sentence)."
        else:  # vs_human
            if p1 > p2:
                prompt = f"Game over: Player 1 beat Player 2 {p1} to {p2}. Brief congrats to Player 1 (1 sentence)."
            elif p2 > p1:
                prompt = f"Game over: Player 2 beat Player 1 {p2} to {p1}. Brief congrats to Player 2 (1 sentence)."
            else:
                prompt = f"Game over: Tie at {p1} each. Short playful tie remark (1 sentence)."
        return call_ollama(prompt)

    def get_miss_commentary(self, player):
        """AI commentary for a miss."""
        player_name = self.get_player_name(player)
        last_mistake = self.mistakes[-1] if self.mistakes else None
        repeated = self.mistakes.count(last_mistake) if last_mistake else 0
        if repeated >= 3:
            prompt = f"{player_name} flipped the same wrong pair {repeated} times. Funny roast (1 sentence)."
        elif self.moves >= self.pairs * 2:
            prompt = f"{player_name} at {self.moves} moves for {self.pairs} pairs. Sarcastic comment (1 sentence)."
        else:
            prompt = f"{player_name} missed. Short sassy comment (1 sentence)."
        return call_ollama(prompt)

    def get_performance_roast(self, player='player1'):
        """Roast about overall performance."""
        player_name = self.get_player_name(player)
        optimal = self.pairs
        current = self.moves
        ratio = current / optimal if optimal > 0 else 1
        if ratio > 3:
            prompt = f"{player_name} took {current} moves for {self.matches}/{self.pairs} pairs (should be ~{optimal}). Savage roast (1 sentence)."
        elif ratio > 2:
            prompt = f"{player_name} at {current} moves, {self.matches}/{self.pairs} matched. Struggling. Roast (1 sentence)."
        else:
            prompt = f"{player_name} doing well - {current} moves, {self.matches}/{self.pairs} pairs. Competitive response (1 sentence)."
        return call_ollama(prompt)

    def get_opponent_move(self):
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
        if not self.opponent_is_ai:
            return None
        profile = self.opponent_profile
        epsilon = profile["epsilon"]
        window = profile["memory_window"]

        # Refresh memory from recent moves
        recent = self.move_history[-window:] if window < 999 else self.move_history
        for move in recent:
            pk = move['pair_key']; cid = move['card_id']
            self.opponent_memory.setdefault(pk, [])
            if cid not in self.opponent_memory[pk]:
                self.opponent_memory[pk].append(cid)

        # Available = unmatched & face-down
        available = [c for c in self.cards if not c['matched'] and not c['flipped']]
        if not available:
            return None

        # Helper: known positions per pair, filtered to those still available
        known_positions = {}
        for pk, ids in self.opponent_memory.items():
            avail_ids = [cid for cid in ids if any(c['id'] == cid and not c['matched'] and not c['flipped'] for c in self.cards)]
            if avail_ids:
                known_positions[pk] = avail_ids

        # 1) If one card is face up now, try to pick its mate if known
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
        seen_ids = set(cid for id_list in self.opponent_memory.values() for cid in id_list)
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
    multiplayer = data.get('multiplayer', False)
    ai_mode = data.get('ai_mode', False) and not multiplayer
    ai_difficulty = data.get('ai_difficulty', 'medium')
    mode = 'vs_human' if multiplayer else ('vs_ai' if ai_mode else 'solo')

    # Daily seed or explicit seed
    daily = data.get('daily', False)
    seed = data.get('seed')
    if daily and seed is None:
        seed = f"{date.today().isoformat()}-{difficulty}-{theme}"

    # Time-attack settings (disabled for multiplayer)
    time_attack = bool(data.get('time_attack', False)) and mode != 'vs_human'
    time_seconds = int(data.get('time_seconds') or 0)

    game = MemoryGame(
        game_id, difficulty, theme=theme, seed=seed,
        time_attack=time_attack, time_seconds=time_seconds,
        mode=mode, opponent_difficulty=ai_difficulty
    )
    games[game_id] = game

    resp = {
        'game_id': game_id,
        'player_token': game.player1_token if mode != 'solo' else None,
        'is_host': True,
        'cards': game.visible_cards(),
        'preview_cards': game.preview_cards(),  # client may ignore
        'pairs': game.pairs,
        'theme': theme,
        'mode': game.mode,
        'player1_score': game.player1_score,
        'player2_score': game.player2_score,
        'player1_accuracy': 0.0,
        'player2_accuracy': 0.0,
        'best_streak': 0,
        'seed': seed,
        'daily': daily,
        'time_attack': game.time_attack,
        'time_seconds': game.time_seconds,
        'player2_joined': game.player2_joined,
        'current_player': game.current_player
    }
    return jsonify(resp)


@app.route('/api/game/<game_id>/join', methods=['POST'])
def join_game(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    if game.mode != 'vs_human' or game.player2_joined:
        return jsonify({'error': 'Cannot join this game'}), 400

    game.player2_token = str(uuid.uuid4())
    game.player2_joined = True

    resp = {
        'game_id': game_id,
        'player_token': game.player2_token,
        'is_host': False,
        'cards': game.visible_cards(),
        'preview_cards': game.preview_cards(),
        'pairs': game.pairs,
        'theme': game.theme,
        'mode': game.mode,
        'player1_score': game.player1_score,
        'player2_score': game.player2_score,
        'player1_accuracy': 0.0,
        'player2_accuracy': 0.0,
        'best_streak': 0,
        'seed': game.seed,
        'daily': False,  # Daily not for multiplayer
        'time_attack': game.time_attack,
        'time_seconds': game.time_seconds,
        'player2_joined': game.player2_joined,
        'current_player': game.current_player
    }
    return jsonify(resp)


@app.route('/api/game/<game_id>/state', methods=['GET'])
def get_game_state(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    token = request.args.get('player_token')
    if game.mode != 'solo':
        is_player1 = token == game.player1_token
        is_player2 = token == game.player2_token
        if not (is_player1 or is_player2):
            return jsonify({'success': False, 'message': 'Invalid token'}), 403

    return jsonify({
        'success': True,
        'cards_state': game.visible_cards(),
        'moves': game.moves,
        'matches': game.matches,
        'player1_score': game.player1_score,
        'player2_score': game.player2_score,
        'current_player': game.current_player,
        'game_won': game.matches == game.pairs,
        'commentary_history': game.commentary_history[-5:],
        'player2_joined': game.player2_joined,
        **game._stats_fragment()
    })


@app.route('/api/game/<game_id>/flip', methods=['POST'])
def flip_card(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404

    game = games[game_id]
    data = request.json or {}
    card_id = data.get('card_id')
    player = data.get('player', 'player1')
    token = data.get('player_token')

    result = game.flip_card(card_id, player, token)
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
    game.player1_score += bonus
    return jsonify({'bonus': bonus, 'player1_score': game.player1_score})


@app.route('/api/game/<game_id>/roast', methods=['GET'])
def get_roast(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    player = request.args.get('player', 'player1')
    roast = game.get_performance_roast(player)
    return jsonify({'roast': roast})


@app.route('/api/game/<game_id>/opponent-move', methods=['GET'])
def opponent_move(game_id):
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    card_id = game.get_opponent_move()
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


@app.route('/api/game/<game_id>/opponent-memory', methods=['GET'])
def opponent_memory(game_id):
    """Expose a tiny view of opponent's memory for the HUD (AI only)."""
    if game_id not in games:
        return jsonify({'error': 'Game not found'}), 404
    game = games[game_id]
    if not game.opponent_is_ai:
        return jsonify({'error': 'Not available'}), 400
    memory = []
    for pk, ids in game.opponent_memory.items():
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
