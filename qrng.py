"""ANU QRNG legacy free-endpoint client with a local disk cache.

Reality check (2026-07): the ANU legacy endpoint (qrng.anu.edu.au/API/jsonI.php)
is now hard rate-limited to **1 request per minute** and returns HTTP 500 with a
rate-limit message if you exceed that. The new endpoint at quantumnumbers.anu.edu.au
requires an API key and is a paid AWS service — explicitly excluded by the
"no paid APIs" scope.

Strategy:
- Default pull size is one request's worth of bytes (1024) so the app boots fast.
- If ANU responds, cache it to disk. The QRNG source is honestly labeled.
- If ANU 5xx's or times out, fall back to OS entropy (`secrets.token_bytes`),
  and label the source `os-fallback` so the UI and thesis can flag any run
  that used it as *not* quantum-sourced.
- A helper `refresh_cache(target_bytes)` can be called from a CLI to grow the
  cache over multiple minutes if a bigger QRNG sample is needed.
"""
import json
import os
import secrets
import time
import urllib.request
import urllib.error
from typing import Tuple

ANU_LEGACY_URL = "https://qrng.anu.edu.au/API/jsonI.php"
CACHE_PATH = "data/qrng_cache.json"
DEFAULT_MIN_BYTES = 1024  # one ANU request under the 1 req/min limit
ANU_RATE_LIMIT_SECONDS = 65

def fetch_anu(length: int = 1024, dtype: str = "uint8", timeout: float = 15.0) -> bytes:
    """Single request to ANU legacy endpoint. length ∈ [1, 1024]."""
    if not (1 <= length <= 1024):
        raise ValueError("length must be in [1, 1024]")
    url = f"{ANU_LEGACY_URL}?length={length}&type={dtype}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"ANU HTTP {e.code}: {e.read().decode()[:200]}") from e
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ANU non-JSON response: {body[:200]}") from e
    if not payload.get("success"):
        raise RuntimeError(f"ANU QRNG returned failure: {payload}")
    if dtype != "uint8":
        raise NotImplementedError("This client only handles uint8 for now.")
    return bytes(payload["data"])

def _write_cache(source: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump({"source": source, "bytes": list(data)}, f)

def load_or_pull(min_bytes: int = DEFAULT_MIN_BYTES) -> Tuple[bytes, str]:
    """Return (bytestream, source) where source ∈ {'anu-cached','anu-fresh','os-fallback'}."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)
        if len(cache.get("bytes", [])) >= min_bytes:
            return bytes(cache["bytes"]), f"{cache.get('source','unknown')}-cached"
    try:
        data = fetch_anu(length=min(min_bytes, 1024))
        _write_cache("anu-legacy", data)
        return data, "anu-fresh"
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, TimeoutError):
        return secrets.token_bytes(min_bytes), "os-fallback"

def refresh_cache(target_bytes: int, sleep_seconds: int = ANU_RATE_LIMIT_SECONDS) -> Tuple[int, str]:
    """CLI helper: pull ANU bytes over multiple minutes, respecting the rate limit.
    Returns (bytes_collected, source). Blocks between requests."""
    collected = bytearray()
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)
        if cache.get("source") == "anu-legacy":
            collected.extend(cache.get("bytes", []))
    while len(collected) < target_bytes:
        try:
            chunk = fetch_anu(length=1024)
            collected.extend(chunk)
            _write_cache("anu-legacy", bytes(collected))
            print(f"got {len(chunk)} bytes, total={len(collected)}/{target_bytes}")
        except RuntimeError as e:
            print(f"fetch failed: {e}. Stopping.")
            break
        if len(collected) < target_bytes:
            time.sleep(sleep_seconds)
    return len(collected), "anu-legacy" if collected else "empty"

if __name__ == "__main__":
    import sys
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
    print(f"Refreshing QRNG cache to {target} bytes (respecting 1 req/min)...")
    n, src = refresh_cache(target)
    print(f"done: {n} bytes cached from {src}")
