"""
Kalshi Edge Detector — Signal Engine
Four-pedal signal chain + volume pro-rating + category efficiency weight.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from kalshi_auth import signed_headers
from odds_keys import get_client as get_odds_client

load_dotenv()

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
API_PATH = "/trade-api/v2"

_SESSION = requests.Session()

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


# ── Fast paginator with retry ────────────────────────────────────────────────
_REQ_DELAY = 0.15   # 150 ms between requests → ~6 req/s, well under rate limit

def _paginate(endpoint, params, list_key, max_items=None):
    """
    Page through a Kalshi endpoint sequentially, returning all items.
    Stops early if max_items is reached. Retries on 429 with exponential backoff.
    Sleeps briefly between pages to stay under Kalshi's rate limit.
    """
    items  = []
    cursor = None

    while True:
        p = {**params}
        if cursor:
            p["cursor"] = cursor

        for attempt in range(4):
            try:
                path = f"{API_PATH}/{endpoint}"
                r = _SESSION.get(
                    f"{BASE_URL}/{endpoint}",
                    headers=signed_headers("GET", path),
                    params=p, timeout=15
                )
                if r.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  ⏳ 429 on /{endpoint} — backing off {wait}s")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except requests.exceptions.HTTPError:
                if attempt == 3:
                    return items
                time.sleep(2 ** attempt)
        else:
            return items

        items.extend(data.get(list_key, []))
        cursor = data.get("cursor")

        if not cursor:
            break
        if max_items and len(items) >= max_items:
            break

        time.sleep(_REQ_DELAY)

    return items


# ── Data fetching ────────────────────────────────────────────────────────────
def fetch_markets_fast():
    """
    Optimized fetch — events-first then direct market pagination.

    Old: 1 events page + 1 call PER event = 100+ requests
    New: paginate /events (3-5 calls) + paginate /markets capped at 2000 (2 calls)
         = ~7 calls total, paced at 150ms → under 2 seconds
    """
    # Step 1: fetch all events → build category lookup (~3-5 calls)
    events = _paginate("events", {"status": "open", "limit": 200}, "events")
    print(f"  → {len(events)} events")

    cat_map = {
        e["event_ticker"]: {
            "category": e.get("category", ""),
            "title":    e.get("title", ""),
        }
        for e in events
    }

    # Step 2: fetch markets for each event (real single-outcome markets only)
    # This avoids KXMVE parlay markets which dominate the generic /markets endpoint
    markets = []
    event_tickers = list(cat_map.keys())[:150]  # cap at 150 events max
    for event_ticker in event_tickers:
        batch = _paginate(
            "markets",
            {"event_ticker": event_ticker, "limit": 100},
            "markets",
        )
        markets.extend(batch)
        if len(markets) >= 2000:
            break
    print(f"  → {len(markets)} real markets (via events)")
    print(f"  → {len(markets)} markets")

    # Step 3: join category data + normalize new dollar-based fields to cents
    for m in markets:
        info = cat_map.get(m.get("event_ticker", ""), {})
        m["_category"]    = info.get("category", "")
        m["_event_title"] = info.get("title", "")

        # Kalshi renamed fields to *_dollars (0.0–1.0). Normalize to cents (0–100).
        try:
            m["yes_bid"] = round(float(m.get("yes_bid_dollars") or 0) * 100, 1)
        except (TypeError, ValueError):
            m["yes_bid"] = 0
        try:
            m["yes_ask"] = round(float(m.get("yes_ask_dollars") or 0) * 100, 1)
        except (TypeError, ValueError):
            m["yes_ask"] = 0
        try:
            m["volume"] = int(float(m.get("volume_fp") or 0))
        except (TypeError, ValueError):
            m["volume"] = 0

    return markets


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
    # Use ask as proxy for mid if bid is zero (no buyers yet)
    if yes_bid == 0 and yes_ask > 0:
        yes_bid = max(yes_ask - 5, 1)

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
        "event_ticker":  m.get("event_ticker", ""),
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
        "sig_cat":       round((p4_cat - 0.8) / (1.2 - 0.8) * 100, 1),
        # Final score
        "score":         score,
        "kelly_size":    size,
    }


def get_scored_markets(max_events=100):
    """Fetch + score all markets. Returns sorted list."""
    raw    = fetch_markets_fast()
    scored = [score_market(m) for m in raw]
    scored = [m for m in scored if m is not None]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ── Sports odds via rotation client ─────────────────────────────────────────

def fetch_sports_odds(sport: str = "basketball_nba", markets: str = "h2h",
                      regions: str = "us", provider: str = None) -> list:
    """
    Fetch live sports odds using the key rotation client.
    Returns list of game objects, or [] on total failure.

    Args:
        sport:    e.g. "basketball_nba", "americanfootball_nfl", "soccer_epl"
        markets:  "h2h" | "spreads" | "totals"
        regions:  "us" | "uk" | "eu" | "au"
        provider: force a specific provider, or None to auto-select
    """
    try:
        client = get_odds_client()
        data, used_provider, key_index = client.get(
            f"/v4/sports/{sport}/odds",
            params={"markets": markets, "regions": regions, "oddsFormat": "decimal"},
            provider=provider,
        )
        print(f"  ✓ Sports odds fetched via [{used_provider}] key_{key_index}")
        return data if isinstance(data, list) else data.get("data", [])
    except RuntimeError as e:
        print(f"  ✗ Sports odds unavailable: {e}")
        return []
    except Exception as e:
        print(f"  ✗ Sports odds fetch error: {e}")
        return []


def get_odds_key_status() -> dict:
    """Return key slot health for all providers — used by the dashboard."""
    try:
        return get_odds_client().key_status()
    except Exception:
        return {}


# ── CLI entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import pandas as pd

    print(f"\n{'='*70}")
    print(f"  KALSHI EDGE  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}\n")
    print("Fetching markets...")

    t0      = time.time()
    markets = get_scored_markets()
    elapsed = round(time.time() - t0, 2)
    print(f"Scored {len(markets)} markets in {elapsed}s\n")

    df = pd.DataFrame(markets)
    cols = ["score", "category", "title", "yes_bid", "yes_ask",
            "volume", "vol_weight", "days_to_close", "kelly_size"]
    df["title"] = df["title"].str[:45]
    print(df[cols].head(25).to_string(index=False))

    os.makedirs("data", exist_ok=True)
    out = f"data/edge_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved → {out}\n")
