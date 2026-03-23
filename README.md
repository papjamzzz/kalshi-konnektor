# kalshi konnektor

> **See what the market misses.**

![kalshi konnektor dashboard](static/screenshots/dashboard.png)

A real-time edge detection dashboard for Kalshi prediction markets. Scores every open market across four independent signals, surfaces the highest-conviction opportunities, and lets you tune the scoring engine live — without restarting anything.  YOU ALONE DIAL IN THAT SPOT UNIQUE TO YOU AND SORT THE JUNK (MOST OF IT) FROM THE TRULY OFF PRICED FUTURES.

---

## The Problem

Kalshi has hundreds of open markets at any given time. Most are efficient. A few aren't — mispriced by volume, time, drift, or category. Finding them manually is slow, inconsistent, and easy to get wrong under pressure.

Kalshi Edge automates the scan and puts the signal front and center.

---

## Features

- 📡 **Live market feed** — pulls all open Kalshi markets via API, refreshes on your schedule
- 🎯 **4-signal scoring engine** — decay, drift, baseline, and category signals scored independently
- 🎛 **KE-1 Signal Processor** — guitar-pedal-style UI with three live knobs that re-rank the table in real time without a page reload
- 📊 **Kelly sizing** — position size suggestions calculated from live score
- 🔍 **Filter + sort** — by category, score, volume, time remaining
- ⭐ **Watchlist** — star markets to pin and track across sessions
- 🌑 **Dark theme** — built for long sessions
- 🔒 **Localhost only** — runs entirely on your machine, never exposed to your network

---

## How It Works

```
Kalshi API
  └── edge.py — fetches markets, computes 4 signals per market
        sig_decay    ← time remaining vs. expected
        sig_drift    ← price movement vs. baseline
        sig_baseline ← absolute price distance from 50¢
        sig_cat      ← category-level edge historical rate
              ↓
      Flask server (app.py) — serves scored data as JSON
              ↓
      Dashboard (index.html)
        KE-1 knobs adjust signal weights in real time
        getLiveScore() rescores and re-ranks the table live
        Kelly sizing updates alongside score
```

---

## Requirements

- macOS
- Python 3.9+
- Kalshi API key ([get one here](https://kalshi.com))

---

## Quick Start

```bash
git clone https://github.com/papjamzzz/kalshi-konnektor.git
cd kalshi-konnektor
```

**Option 1 — Double-click launcher (Mac)**
Double-click `launch.command` in Finder. First run will ask for your API key and sets everything up automatically.

**Option 2 — Terminal**
```bash
make setup      # creates venv, installs dependencies
make run        # starts the server
```

Then open **http://localhost:5555** in your browser.

---

## The KE-1 Signal Processor

The pedal board at the top of the dashboard gives you live control over how markets are scored:

| Knob | What It Does |
|------|-------------|
| **Signal** | Overall score multiplier — scales all signals up or down |
| **Depth** | Volume weighting — how much liquidity factors into edge |
| **Time** | Decay weighting — how much time remaining affects the score |
| **Bypass** | Disables all knobs and uses raw signal scores |

Changes take effect instantly — the table re-ranks as you turn the knobs.

---

## Project Structure

```
kalshi-konnektor/
├── app.py              ← Flask server (localhost only, port 5555)
├── edge.py             ← Signal scoring engine
├── templates/
│   └── index.html      ← Full dashboard + KE-1 UI
├── static/             ← Logo and static assets
├── data/               ← Auto-saved market snapshots
├── requirements.txt
├── launch.command      ← Mac double-click launcher
├── Makefile            ← make setup / make run / make zip
└── .env.example        ← API key template
```

---

## Configuration

Copy `.env.example` to `.env` and add your Kalshi API key:

```
KALSHI_API_KEY=your-key-here
```

---

## Security

- Server binds to `127.0.0.1` — only accessible from your own machine
- API key stored in `.env`, never committed to version control
- No data leaves your machine

---

## Disclaimer

This tool is for research and signal exploration only. It does not place trades, manage funds, or guarantee outcomes. Not financial advice.

---

## License

MIT

---

*Built for traders who want an edge, not a guess.*


---

## Part of Creative Konsoles

Built by [Creative Konsoles](https://creativekonsoles.com) — tools built using thought.

**[creativekonsoles.com](https://creativekonsoles.com)** &nbsp;·&nbsp; support@creativekonsoles.com
