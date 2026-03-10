"""
Kalshi Edge Detector — Signal Engine
Four-pedal signal chain + volume pro-rating + category efficiency weight.
"""

import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_KEY  = os.getenv("KALSHI_API_KEY")
BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
HEADERS  = {
    "Authorization": f"Token {API_KEY}",
    "Content-Type": "application/json",
}

# ── Volume bounds ────────────────────────────────────────────────────────────
LOW_VOL  = 500
HIGH_VOL = 100_000

# ── Category efficiency weights (less efficient = higher weight = more edge) ─
CATEGORY_WEIGHT = {
    "Entertainment":          1.20,
    "Companies":              1.10,
    "Science and Technology": 1.05,
    "World":                  1.00,
    "Economics":              0.90,
    "Politics":               0.80,
}


# ── Pedal 1: Time decay ──────────────────────────────────────────────────────
def time_decay_factor(close_time_str):
    """
    More time remaining → more opportunity for mispricing to persist.
    Normalized over 30 days (720h). Returns 0.0–1.0.
    """
    if not close_time_str:
        return 0.5
    try:
        close = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
        hours = max((close - datetime.now(timezone.utc)).total_seconds() / 3600, 0)
        return min(hours / 720, 1.0)
    except Exception:
        return 0.5


# ── Pedal 2: Spread width (uncertainty proxy) ────────────────────────────────
def odds_drift_score(yes_bid, yes_ask):
    """
    Wide spread → market hasn't converged → edge opportunity.
    Returns 0.0–1.0.
    """
    if yes_bid is None or yes_ask is None:
        return 0.0
    return min((yes_ask - yes_bid) / 100, 1.0)


# ── Pedal 3: Distance from 50/50 baseline ───────────────────────────────────
def baseline_deviation(yes_price):
    """
    Near 50% = genuine uncertainty = most likely mispriced.
    Near 0/100 = crowd has high conviction = less edge.
    Returns 0.0–1.0 (peaks at 50%).
    """
    if yes_price is None:
        return 0.0
    return 1.0 - abs(yes_price - 50) / 50


# ── Pedal 4: Category efficiency ────────────────────────────────────────────
def category_efficiency(category):
    """
    Entertainment & niche markets = less analyst attention = more mispricing.
    Politics & economics = heavily traded = more efficient.
    Returns multiplier 0.80–1.20.
    """
    return CATEGORY_WEIGHT.get(category, 1.0)


# ── Volume pro-rating ────────────────────────────────────────────────────────
def volume_weight(volume):
    """
    Thin markets → boost signal (overlooked/mispriced).
    Liquid markets → dampen signal (crowd has corrected it).
    Linear between LOW_VOL (2.0x) and HIGH_VOL (0.25x).
    """
    v = volume or 0
    if v == 0:         return 1.5
    if v <= LOW_VOL:   return 2.0
    if v >= HIGH_VOL:  return 0.25
    ratio = (v - LOW_VOL) / (HIGH_VOL - LOW_VOL)
    return round(2.0 - ratio * (2.0 - 0.25), 3)


def vol_tier_label(volume):
    v = volume or 0
    if v == 0:       return "ghost"
    if v <= 100:     return "thin"
    if v <= 1_000:   return "active"
    if v <= 10_000:  return "liquid"
    return "deep"


# ── Data fetching ────────────────────────────────────────────────────────────
def fetch_markets_by_event(max_events=100):
    """Pull events → fetch their markets. Returns raw market list with category attached."""
    all_markets = []
    cursor = None

    while True:
        params = {"status": "open", "limit": 100}
        if cursor:
            params["cursor"] = cursor

        resp = requests.get(f"{BASE_URL}/events", headers=HEADERS, params=params)
        resp.raise_for_status()
        data    = resp.json()
        events  = data.get("events", [])

        if not events:
            break

        for event in events:
            if len(all_markets) >= max_events * 8:
                break
            ticker = event.get("event_ticker", "")
            mresp  = requests.get(
                f"{BASE_URL}/markets",
                headers=HEADERS,
                params={"event_ticker": ticker, "status": "open"},
            )
            if mresp.status_code == 200:
                ms = mresp.json().get("markets", [])
                for m in ms:
                    m["_category"]    = event.get("category", "")
                    m["_event_title"] = event.get("title", "")
                all_markets.extend(ms)

        cursor = data.get("cursor")
        if not cursor or len(all_markets) >= max_events * 8:
            break

    return all_markets


# ── Scoring ──────────────────────────────────────────────────────────────────
def score_market(m):
    """Score a single market. Returns enriched dict or None if unscorable."""
    yes_bid   = m.get("yes_bid")
    yes_ask   = m.get("yes_ask")
    category  = m.get("_category", "")

    if yes_bid is None or yes_ask is None:
        return None
    if yes_bid == 0 and yes_ask == 0:
        return None

    yes_price = (yes_bid + yes_ask) / 2
    volume    = m.get("volume") or 0
    close_str = m.get("close_time") or m.get("expected_expiration_time") or ""

    # ── Run pedals ───────────────────────────────────────────────────────────
    p1_decay    = time_decay_factor(close_str)
    p2_drift    = odds_drift_score(yes_bid, yes_ask)
    p3_baseline = baseline_deviation(yes_price)
    p4_cat      = category_efficiency(category)
    vol_w       = volume_weight(volume)

    raw   = (p1_decay + p2_drift + p3_baseline) / 3   # 0–1
    score = round(min(raw * p4_cat * vol_w * 50, 100), 1)

    if score == 0:
        return None

    # ── Days to close ────────────────────────────────────────────────────────
    days_to_close = None
    if close_str:
        try:
            close = datetime.fromisoformat(close_str.replace("Z", "+00:00"))
            days_to_close = max((close - datetime.now(timezone.utc)).days, 0)
        except Exception:
            pass

    # ── Kelly-inspired sizing ─────────────────────────────────────────────
    if score >= 70:   size = "2–3%"
    elif score >= 60: size = "1–2%"
    elif score >= 50: size = "0.5–1%"
    else:             size = "watch"

    return {
        # Identity
        "ticker":        m.get("ticker", ""),
        "category":      category,
        "event_title":   m.get("_event_title", ""),
        "title":         m.get("title", ""),
        # Pricing
        "yes_bid":       yes_bid,
        "yes_ask":       yes_ask,
        "mid":           round(yes_price, 1),
        "spread":        yes_ask - yes_bid,
        # Volume
        "volume":        volume,
        "vol_tier":      vol_tier_label(volume),
        "vol_weight":    vol_w,
        # Time
        "close":         close_str[:10],
        "days_to_close": days_to_close,
        # Signal breakdown (each 0–100 for display)
        "sig_decay":     round(p1_decay * 100, 1),
        "sig_drift":     round(p2_drift * 100, 1),
        "sig_baseline":  round(p3_baseline * 100, 1),
        "sig_cat":       round((p4_cat - 0.8) / (1.2 - 0.8) * 100, 1),  # normalize 0.8–1.2 → 0–100
        # Final score
        "score":         score,
        "kelly_size":    size,
    }


def get_scored_markets(max_events=100):
    """Fetch + score all markets. Returns sorted list."""
    raw     = fetch_markets_by_event(max_events)
    scored  = [score_market(m) for m in raw]
    scored  = [m for m in scored if m is not None]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ── CLI entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pandas as pd

    print(f"\n{'='*70}")
    print(f"  KALSHI EDGE  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")
    print("Fetching markets...")

    markets = get_scored_markets()
    print(f"Scored {len(markets)} markets\n")

    df = pd.DataFrame(markets)
    cols = ["score", "category", "title", "yes_bid", "yes_ask",
            "volume", "vol_weight", "days_to_close", "kelly_size"]
    df["title"] = df["title"].str[:45]
    print(df[cols].head(25).to_string(index=False))

    os.makedirs("data", exist_ok=True)
    out = f"data/edge_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved → {out}\n")
