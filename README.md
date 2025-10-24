# 🎮 AI-Powered Memory Game

A fast, fun memory card game with Pokémon/Emoji/Flag themes, **Time‑Attack**, **SFX + mute**, optional **AI opponent**, and playful **AI roast** commentary (via Ollama).

---

## 📦 Project
```
ai-memory-game/
├── app.py
├── templates/
│   └── index.html
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start
1) Install deps
```bash
pip install -r requirements.txt
```
2) (Optional) Enable roasts with Ollama
```bash
ollama pull llama3.2
ollama serve
```
3) Run
```bash
flask run
```
Open **http://localhost:5000**.

---

## 🎮 Play
- **Modes**: Solo • vs AI (Easy/Hard)
- **Difficulty**: Easy (6 pairs) • Medium (8) • Hard (12)
- **Rules**: Flip two cards → match stays ✅, miss flips back ❌. Match all pairs to win 🏆.
- **Time‑Attack (optional)**: 60/90/120s timer + small score bonus if time remains.

---

## ✨ Features
- **Themes**: Pokémon (online), Emoji (offline), Flags (offline)
- **AI Opponent**: Easy or Hard
- **AI Roast**: Local LLM quips via Ollama (falls back to canned lines if off)
- **Hints**: Highlight your last missed pair positions
- **SFX + Mute**: Flip / match / miss / timer tick
- **Daily Puzzle**: Deterministic seeded board
- **Stats & History**: Moves, accuracy, streak, timeline

> Tip: Offline demo? Use **Emoji** or **Flags** themes.

---

## 🛠 Notes
- Pokémon images need internet (PokéAPI). Emoji/Flags are fully offline.
- No roasts? Start Ollama, or ignore (fallback messages are used).

---

## ⚠️ Troubleshooting
- **No sound**: Click once to enable audio (browser gesture).
- **Port busy**: Edit the port in `app.py` (e.g., 5001).
- **Pokémon images missing**: Check network or switch to Emoji/Flags.
- **Ollama**: `ollama pull llama3.2 && ollama serve`.

---
