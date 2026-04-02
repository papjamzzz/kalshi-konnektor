"""
Kalshi Edge Detector — Flask Dashboard Server
Run:  python3 app.py
Open: http://localhost:5555
"""

import json
import os
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

from edge import get_scored_markets, volume_weight, fetch_sports_odds, get_odds_key_status

app = Flask(__name__)

# ── In-memory cache ──────────────────────────────────────────────────────────
_cache = {
    "data":      None,
    "timestamp": 0,
    "ttl":       600,   # seconds before stale (10 min)
    "fetching":  False,
}


def refresh_cache(force=False):
    now = time.time()
    age = now - _cache["timestamp"]

    if not force and _cache["data"] is not None and age < _cache["ttl"]:
        return _cache["data"]

    if _cache["fetching"]:
        return _cache["data"] or []

    _cache["fetching"] = True
    try:
        markets = get_scored_markets(max_events=100)
        _cache["data"]      = markets
        _cache["timestamp"] = time.time()

        # Persist snapshot for historical tracking
        _save_snapshot(markets)
        return markets
    except Exception as e:
        # On any fetch error (rate limit, network, etc.) return stale data
        # rather than crashing — dashboard stays usable
        print(f"  ⚠ Fetch error (returning stale): {e}")
        return _cache["data"] or []
    finally:
        _cache["fetching"] = False


def _save_snapshot(markets):
    os.makedirs("data", exist_ok=True)
    snap = {
        "timestamp": datetime.now().isoformat(),
        "markets":   markets,
    }
    fname = f"data/snap_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(fname, "w") as f:
        json.dump(snap, f)


def _load_snapshots(limit=60):
    """Return list of (timestamp, markets) tuples from saved snapshots."""
    data_dir = "data"
    if not os.path.exists(data_dir):
        return []
    files = sorted(
        f for f in os.listdir(data_dir)
        if f.startswith("snap_") and f.endswith(".json")
    )[-limit:]
    snaps = []
    for fname in files:
        try:
            with open(os.path.join(data_dir, fname)) as f:
                snap = json.load(f)
            snaps.append(snap)
        except Exception:
            pass
    return snaps


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/markets")
def api_markets():
    force   = request.args.get("refresh") == "1"
    markets = refresh_cache(force=force)

    categories = sorted(set(m["category"] for m in markets if m.get("category")))
    cache_age  = round(time.time() - _cache["timestamp"]) if _cache["timestamp"] else None

    return jsonify({
        "markets":    markets,
        "total":      len(markets),
        "categories": categories,
        "timestamp":  datetime.fromtimestamp(_cache["timestamp"]).isoformat()
                      if _cache["timestamp"] else None,
        "cache_age":  cache_age,
        "top_score":  markets[0]["score"] if markets else 0,
        "avg_score":  round(sum(m["score"] for m in markets) / len(markets), 1)
                      if markets else 0,
    })


@app.route("/api/history/<path:ticker>")
def api_history(ticker):
    """Return score history for a specific market ticker."""
    snaps   = _load_snapshots(limit=100)
    history = []
    for snap in snaps:
        for m in snap.get("markets", []):
            if m.get("ticker") == ticker:
                history.append({
                    "ts":      snap["timestamp"],
                    "score":   m["score"],
                    "yes_bid": m["yes_bid"],
                    "yes_ask": m["yes_ask"],
                    "volume":  m["volume"],
                })
                break
    return jsonify(history)


@app.route("/api/movers")
def api_movers():
    """Compare current snapshot to the previous one and return top movers."""
    snaps = _load_snapshots(limit=2)
    if len(snaps) < 2:
        return jsonify([])

    prev = {m["ticker"]: m["score"] for m in snaps[-2].get("markets", [])}
    curr = snaps[-1].get("markets", [])

    movers = []
    for m in curr:
        t = m["ticker"]
        if t in prev:
            delta = round(m["score"] - prev[t], 1)
            if abs(delta) >= 1.0:
                movers.append({**m, "delta": delta})

    movers.sort(key=lambda x: abs(x["delta"]), reverse=True)
    return jsonify(movers[:15])


@app.route("/api/stats")
def api_stats():
    """Category breakdown and distribution stats."""
    markets = _cache["data"] or []
    if not markets:
        return jsonify({})

    from collections import Counter
    cat_counts  = Counter(m["category"] for m in markets)
    tier_counts = Counter(m["vol_tier"] for m in markets)
    score_dist  = {
        "70+":   sum(1 for m in markets if m["score"] >= 70),
        "60-70": sum(1 for m in markets if 60 <= m["score"] < 70),
        "50-60": sum(1 for m in markets if 50 <= m["score"] < 60),
        "<50":   sum(1 for m in markets if m["score"] < 50),
    }

    return jsonify({
        "by_category": dict(cat_counts),
        "by_vol_tier": dict(tier_counts),
        "score_dist":  score_dist,
        "total":       len(markets),
        "top_score":   markets[0]["score"] if markets else 0,
        "avg_score":   round(sum(m["score"] for m in markets) / len(markets), 1),
    })


# ── Sports odds routes ───────────────────────────────────────────────────────

@app.route("/api/odds")
def api_odds():
    """
    Fetch live sports odds via key rotation.
    Query params:
      sport    — default: basketball_nba
      markets  — default: h2h
      regions  — default: us
      provider — optional: sportsoddsapi | pinnacle
    """
    sport    = request.args.get("sport",    "basketball_nba")
    markets  = request.args.get("markets",  "h2h")
    regions  = request.args.get("regions",  "us")
    provider = request.args.get("provider", None)

    data = fetch_sports_odds(sport=sport, markets=markets,
                             regions=regions, provider=provider)
    return jsonify({"sport": sport, "markets": markets,
                    "count": len(data), "data": data})


@app.route("/api/odds-status")
def api_odds_status():
    """Return key slot health for all providers."""
    return jsonify(get_odds_key_status())


# ── Startup ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import threading

    def background_load():
        print("  Fetching market data in background...")
        refresh_cache(force=True)
        print(f"  ✓ Loaded {len(_cache['data'] or [])} markets\n")

    print("\n" + "=" * 55)
    print("  ⚡ KALSHI EDGE DETECTOR")
    print("=" * 55)
    print("  Open: http://localhost:5555")
    print("  Markets loading in background — page is live now")
    print("=" * 55 + "\n")

    t = threading.Thread(target=background_load, daemon=True)
    t.start()

    app.run(debug=False, port=5555, host="127.0.0.1")
