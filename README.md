# 🎮 AI-Powered Memory Game

A fast, fun memory card game with Pokémon/Emoji/Flag themes, **Time‑Attack**, **SFX + mute**, optional **AI opponent**, playful **AI roast** commentary (via Ollama), and **real‑time Multiplayer** with synced flips + secure turn‑taking.

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
```
pip install -r requirements.txt
```
2) (Optional) Enable roasts with Ollama
```
ollama pull llama3.2
ollama serve
```
3) Run
```
flask run
```
Open http://localhost:5000

---

## 🎮 Play
- **Modes**: Solo • vs AI (Easy/Medium/Hard) • **Multiplayer (2 players)**
- **Difficulty**: Easy (6 pairs) • Medium (8) • Hard (12)
- **Rules**: Flip two cards → match stays ✅, miss flips back ❌. Match all pairs to win 🏆.
- **Time‑Attack (optional)**: 60/90/120s timer + small score bonus if time remains.

---

## 👥 Multiplayer
- Join a shared board with a **Game ID** (host starts, friend joins).
- **Secure turn‑taking** (server-enforced tokens and current turn).
- **Live sync** of flips, scores, and **AI Judge** commentary.
- **Smooth misses**: non-matching pairs cleanly flip back on both screens (graceful polling + auto-reset fallback).

---

## ✨ Features
- **Themes**: Pokémon (online), Emoji (offline), Flags (offline)
- **AI Opponent**: Easy / Medium / Hard
- **AI Roast**: Local LLM quips via Ollama (falls back to canned lines if off)
- **Hints**: Highlight your last missed pair positions
- **SFX + Mute**: Flip / match / miss / timer tick
- **Daily Puzzle**: Deterministic seeded board
- **Stats & History**: Moves, accuracy, streak, timeline
- **Accessibility**: Reduced-motion friendly; responsive layout

> Tip: Offline demo? Use **Emoji** or **Flags** themes.

---

## 🛠 Notes
- Pokémon images need internet (PokéAPI). Emoji/Flags are fully offline.
- Start Ollama, or ignore (fallback messages are used).

---

## 🛠 Troubleshooting
- **Player 2 can’t act**: Ensure the server is returning `current_player` and client trusts it (included in this repo).
- **Cards stay face-up after opponent misses**: Client's polling “graceful handoff” is included; verify you didn’t remove the `hasTransientFaceUps` check or the timed `/reset` safety net.
- **No sound**: Click once to enable audio (browser gesture).
- **Port busy**: Change the port in `app.py` (e.g., 5001).
- **Pokémon images missing**: Check network or switch to Emoji/Flags.
- **Ollama**: `ollama pull llama3.2 && ollama serve`.

---
