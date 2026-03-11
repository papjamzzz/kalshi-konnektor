# Kalshi Edge — Project Re-Entry File
*Claude: read this before touching anything.*

---

## What This Is
A prediction market edge detector for Kalshi.
Dark-theme Flask dashboard. Runs locally. Scores markets using 4 signals.
User is the only end-user (runs on their own Mac).

## Re-Entry Phrase
> "Re-entry: Kalshi Edge"

## Current Status — ✅ SHIPPED
- Signal engine: `edge.py`
- Flask server: `app.py` (port 5555, localhost only)
- Dashboard: `templates/index.html`
- KE-1 pedal board UI with 3 live knobs (signal, depth, time) + bypass
- Slogan: "See what the market misses." (in header)
- Logo slot: `/static/logo.png` (drop file in — auto appears, no code needed)
- GitHub: https://github.com/papjamzzz/kalshi-konnektor

## File Structure
```
kalshi-edge/
├── app.py              ← Flask server (host=127.0.0.1, port=5555)
├── edge.py             ← Signal scoring engine
├── templates/
│   └── index.html      ← Full dashboard (dark theme)
├── static/             ← Drop logo.png here
├── data/               ← Auto-generated market snapshots
├── requirements.txt
├── launch.command      ← Double-click to run on Mac
├── Makefile            ← make setup / make run / make zip
├── .env                ← API key (never commit)
└── .env.example        ← Safe template
```

## How to Run
```bash
# Option 1 — double-click launch.command in Finder
# Option 2 — terminal:
cd ~/kalshi-edge
make run
```

## Pipeline Compliance
✅ Follows ~/.claude/PIPELINE.md standard
- .gitignore ✅ | Makefile w/ push target ✅ | launch.command w/ pkill ✅ | .env.example ✅

## What's Next (pick up here)
- [ ] Add logo.png to static/ when user gets their logo
- [ ] Update README.md on GitHub with real description
- [ ] Audit dashboard — confirm live data flowing, knobs working
- [ ] Consider: private vs public repo decision

## Key Technical Decisions
- `host=127.0.0.1` — localhost only, not visible on LAN
- Live scoring via `getLiveScore(m)` — knobs affect table in real time
- `onerror="this.style.display='none'"` on logo — graceful if file missing
- `.env` excluded from git — API key never pushed

## Pushing Changes to GitHub
```bash
cd ~/kalshi-edge
git add .
git commit -m "describe what changed"
git push origin main
# Username: papjamzzz
# Password: mac-push token (saved in Notes)
```

---
*Last updated: 2026-03-10*
