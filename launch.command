#!/bin/bash
# ──────────────────────────────────────────────────────────────
#  ⚡ KALSHI EDGE DETECTOR — Launch Script
#  Double-click this file in Finder to start the app.
#  First run: installs everything. After that: instant.
# ──────────────────────────────────────────────────────────────

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo ""
echo "══════════════════════════════════════════"
echo "  ⚡ KALSHI EDGE DETECTOR"
echo "══════════════════════════════════════════"

# ── First-run: ask for API key ────────────────────────────────
if [ ! -f ".env" ]; then
  echo ""
  echo "  First-time setup — takes about 30 seconds."
  echo ""
  read -p "  Enter your Kalshi API key: " API_KEY
  echo "KALSHI_API_KEY=$API_KEY" > .env
  echo ""
  echo "  ✓ API key saved to .env"
fi

# ── Create virtualenv if needed ───────────────────────────────
if [ ! -d "venv" ]; then
  echo ""
  echo "  Installing dependencies (one-time)..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt -q
  echo "  ✓ Dependencies installed."
else
  source venv/bin/activate
fi

# ── Open browser after short delay ───────────────────────────
sleep 3 && open http://localhost:5555 &

echo ""
echo "  → http://localhost:5555"
echo "  Press Ctrl+C to stop."
echo "══════════════════════════════════════════"
echo ""

python3 app.py
