"""Fetch the current estimated top prize / jackpot from each Texas
Lottery game's official index page.

Scrape target per game (verified 2026-07-10):
- Lotto Texas / Mega Millions / Powerball / Texas Two Step: dynamic
  rolling jackpot published under "Estimated Jackpot" on the game's
  index.html. First dollar value inside a ~500-char window after that
  string is the current top prize.
- Cash Five / All or Nothing / Pick 3 / Daily 4: fixed top prizes,
  no page scraping needed — returned as static strings so the UI
  can always render the "top prize" line.

Failures are silent (return None). Caller should hide the row rather
than surface an error.
"""
from __future__ import annotations
import re
import urllib.request
from typing import Optional

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_AMOUNT_RE = re.compile(
    r"\$([\d,]+(?:\.\d+)?)\s*(Million|Billion|Thousand)?",
    re.IGNORECASE,
)

_GAMES_WITH_ROLLING_JACKPOT = {
    "Lotto Texas", "Mega Millions", "Powerball", "Texas Two Step",
}

# Fixed prizes shown as-is. For digit games the tier isn't a "jackpot"
# in the rolling sense; we still show the top straight-play prize so
# the user sees consistent info across every card.
_FIXED_TOP_PRIZES = {
    "Cash Five":      "$25,000",
    "All or Nothing": "$250,000",
    "Pick 3":         "$500 (Straight, $1 play)",
    "Daily 4":        "$5,000 (Straight, $1 play)",
}


def game_url(game_name: str) -> str:
    """Official Texas Lottery page URL for the game."""
    return ("https://www.texaslottery.com/export/sites/lottery/Games/"
            f"{game_name.replace(' ', '_')}/index.html")


def _parse_jackpot(html: str) -> Optional[str]:
    """Extract '$X Million' / '$X,XXX' style top prize from a game page."""
    text = _WS_RE.sub(" ", _TAG_RE.sub(" ", html))
    idx = text.find("Estimated Jackpot")
    if idx == -1:
        return None
    m = _AMOUNT_RE.search(text, idx, idx + 500)
    if not m:
        return None
    amount, suffix = m.group(1), m.group(2)
    return f"${amount} {suffix}".strip() if suffix else f"${amount}"


def fetch_top_prize(game_name: str, timeout: float = 4.0) -> Optional[str]:
    """Return a display string for the current top prize, or None on any
    scrape failure. Fixed-prize games always return their static string.
    """
    if game_name in _FIXED_TOP_PRIZES:
        return _FIXED_TOP_PRIZES[game_name]
    if game_name not in _GAMES_WITH_ROLLING_JACKPOT:
        return None
    try:
        req = urllib.request.Request(
            game_url(game_name),
            headers={"User-Agent": "lotto-app/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    return _parse_jackpot(html)


def fetch_all_top_prizes(timeout: float = 4.0) -> dict:
    """Fetch every game's top prize concurrently. Fixed-prize games short-
    circuit; rolling-jackpot games run in parallel threads so total wall
    time is bounded by the slowest single request, not their sum. Any
    thread that fails contributes None (no error surfaced)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    result: dict = {}
    rolling: list = []
    for name in GAMES_ALL:
        if name in _FIXED_TOP_PRIZES:
            result[name] = _FIXED_TOP_PRIZES[name]
        elif name in _GAMES_WITH_ROLLING_JACKPOT:
            rolling.append(name)
        else:
            result[name] = None
    with ThreadPoolExecutor(max_workers=len(rolling) or 1) as pool:
        futures = {
            pool.submit(fetch_top_prize, name, timeout): name
            for name in rolling
        }
        for fut in as_completed(futures):
            result[futures[fut]] = fut.result()
    return result


# Names for the parallel fetcher — declared here so we don't import GAMES
# and cause a circular reference at module load.
GAMES_ALL = (
    "Lotto Texas", "Mega Millions", "Powerball", "Cash Five",
    "Texas Two Step", "All or Nothing", "Pick 3", "Daily 4",
)
