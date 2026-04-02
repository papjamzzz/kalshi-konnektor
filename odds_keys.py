"""
odds_keys.py — Multi-provider sports odds API key rotation
-----------------------------------------------------------
Supports up to 10 keys per provider. On 429/402, parks that key
for the duration of Retry-After and falls through to the next slot.
On 401/403, marks the key exhausted for the session.

Env var naming convention:
  SPORTSODDSAPI_KEY_1 … SPORTSODDSAPI_KEY_10
  PINNACLE_KEY_1     … PINNACLE_KEY_10

Usage:
  from odds_keys import OddsClient
  client = OddsClient()
  data, provider, key_slot = client.get("/v4/sports/basketball_nba/odds", params={"regions": "us"})
"""

import os
import time
import threading
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Provider registry ─────────────────────────────────────────────────────────
# Add new providers here. Each needs a base_url and env_prefix.
PROVIDERS = {
    "sportsoddsapi": {
        "label":      "The Odds API",
        "base_url":   "https://api.the-odds-api.com",
        "env_prefix": "SPORTSODDSAPI_KEY",
        "key_param":  "apiKey",        # injected as a query param
        "auth_header": None,           # or e.g. "X-Api-Key" for header auth
    },
    "pinnacle": {
        "label":      "Pinnacle",
        "base_url":   "https://api.pinnacle.com",
        "env_prefix": "PINNACLE_KEY",
        "key_param":  None,
        "auth_header": "Authorization",  # "Basic <base64>" — set full value in env
    },
    # ── Template for adding a new provider ───────────────────────────────────
    # "betfair": {
    #     "label":      "Betfair",
    #     "base_url":   "https://api.betfair.com",
    #     "env_prefix": "BETFAIR_KEY",
    #     "key_param":  None,
    #     "auth_header": "X-Authentication",
    # },
}

MAX_KEYS   = 10      # slots per provider (KEY_1 … KEY_10)
TIMEOUT    = 12      # request timeout in seconds
MAX_RETRY  = 3       # retries per key before moving on


# ── Key slot state ────────────────────────────────────────────────────────────

class _KeySlot:
    def __init__(self, provider: str, index: int, key: str):
        self.provider    = provider
        self.index       = index
        self.key         = key
        self.exhausted   = False        # 401/403 — permanently bad this session
        self.parked_until = 0.0         # epoch — parked on 429, try again after

    def is_available(self) -> bool:
        if self.exhausted:
            return False
        if time.time() < self.parked_until:
            return False
        return True

    def park(self, seconds: float):
        self.parked_until = time.time() + seconds
        print(f"  ⏳ [{self.provider}] key_{self.index} parked for {seconds:.0f}s")

    def exhaust(self):
        self.exhausted = True
        print(f"  ✗  [{self.provider}] key_{self.index} exhausted (401/403)")

    @property
    def status(self) -> str:
        if self.exhausted:
            return "exhausted"
        wait = self.parked_until - time.time()
        if wait > 0:
            return f"parked_{int(wait)}s"
        return "ready"


# ── Main client ───────────────────────────────────────────────────────────────

class OddsClient:
    def __init__(self):
        self._lock   = threading.Lock()
        self._slots: dict[str, list[_KeySlot]] = {}
        self._load_all_keys()

    def _load_all_keys(self):
        """Read keys from env for every registered provider."""
        for provider, cfg in PROVIDERS.items():
            prefix = cfg["env_prefix"]
            slots  = []
            for i in range(1, MAX_KEYS + 1):
                key = os.getenv(f"{prefix}_{i}", "").strip()
                if key:
                    slots.append(_KeySlot(provider, i, key))
            self._slots[provider] = slots
            if slots:
                print(f"  ✓ [{provider}] {len(slots)} key(s) loaded")
            else:
                print(f"  ○ [{provider}] no keys found — set {prefix}_1 … _{MAX_KEYS} in .env")

    def reload_keys(self):
        """Hot-reload keys from env without restarting. Safe to call anytime."""
        with self._lock:
            load_dotenv(override=True)
            self._load_all_keys()
            print("  ↺  Keys reloaded from env")

    def key_status(self) -> dict:
        """Return current slot status for all providers — for the dashboard."""
        out = {}
        for provider, slots in self._slots.items():
            out[provider] = {
                "label":  PROVIDERS[provider]["label"],
                "total":  len(slots),
                "ready":  sum(1 for s in slots if s.status == "ready"),
                "slots":  [{"index": s.index, "status": s.status} for s in slots],
            }
        return out

    def get(self, path: str, params: dict = None, provider: str = None) -> tuple:
        """
        Make a GET request, rotating keys on failure.

        Args:
            path:     API path, e.g. "/v4/sports/basketball_nba/odds"
            params:   Additional query params (do NOT include the API key here)
            provider: Which provider to use. If None, tries providers in order.

        Returns:
            (data: dict, provider_used: str, key_index: int)

        Raises:
            RuntimeError if all keys across all tried providers are unavailable.
        """
        params = params or {}
        providers_to_try = [provider] if provider else list(PROVIDERS.keys())

        last_error = None
        for prov in providers_to_try:
            cfg   = PROVIDERS.get(prov)
            slots = self._slots.get(prov, [])
            if not cfg or not slots:
                continue

            result = self._try_provider(prov, cfg, slots, path, params)
            if result is not None:
                return result
            last_error = prov

        raise RuntimeError(
            f"All keys exhausted or parked for providers: {providers_to_try}. "
            f"Add more keys or wait for parked keys to recover."
        )

    def _try_provider(self, provider, cfg, slots, path, params):
        """Try each available key slot for a provider. Returns (data, provider, index) or None."""
        base_url = cfg["base_url"]
        url      = base_url.rstrip("/") + "/" + path.lstrip("/")

        for slot in slots:
            with self._lock:
                if not slot.is_available():
                    continue

            for attempt in range(MAX_RETRY):
                try:
                    req_params  = dict(params)
                    req_headers = {}

                    # Inject auth — param or header
                    if cfg["key_param"]:
                        req_params[cfg["key_param"]] = slot.key
                    elif cfg["auth_header"]:
                        req_headers[cfg["auth_header"]] = slot.key

                    r = requests.get(url, params=req_params, headers=req_headers,
                                     timeout=TIMEOUT)

                    # ── 200 ─────────────────────────────────────────────────
                    if r.status_code == 200:
                        return (r.json(), provider, slot.index)

                    # ── Rate limit — park and try next key ──────────────────
                    if r.status_code in (429, 402):
                        retry_after = float(r.headers.get("Retry-After", 60))
                        slot.park(retry_after)
                        break   # move to next slot immediately

                    # ── Bad key — exhaust it ─────────────────────────────────
                    if r.status_code in (401, 403):
                        slot.exhaust()
                        break

                    # ── Server error — retry with backoff ───────────────────
                    if r.status_code >= 500:
                        if attempt < MAX_RETRY - 1:
                            time.sleep(2 ** attempt)
                            continue
                        print(f"  ✗ [{provider}] key_{slot.index} got {r.status_code} after {MAX_RETRY} tries")
                        break

                    # ── Other 4xx — log and skip ────────────────────────────
                    print(f"  ✗ [{provider}] key_{slot.index} got {r.status_code}: {r.text[:80]}")
                    break

                except requests.exceptions.Timeout:
                    print(f"  ✗ [{provider}] key_{slot.index} timed out (attempt {attempt+1})")
                    if attempt < MAX_RETRY - 1:
                        time.sleep(1)
                    continue
                except requests.exceptions.RequestException as e:
                    print(f"  ✗ [{provider}] key_{slot.index} request error: {e}")
                    break

        return None   # all slots for this provider failed


# ── Singleton — import once, use everywhere ───────────────────────────────────
_client: OddsClient | None = None

def get_client() -> OddsClient:
    global _client
    if _client is None:
        _client = OddsClient()
    return _client
