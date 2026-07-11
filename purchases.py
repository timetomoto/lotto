"""Walk-forward simulation of buying one ticket per draw using the app's
S1 numbers as they would have appeared at each draw's date.

Semantics:
  At each historical draw t (past a 50-draw burn-in), the "player" is
  assumed to have bought a ticket with S1_t — where S1_t is the top-K
  most-frequent balls computed from draws BEFORE t, matching what the
  app's Overview card would have shown at that moment. For games with a
  bonus pool (Powerball, Mega Millions, Texas Two Step) the ticket also
  includes the walk-forward top-1 bonus ball at that same moment.

Cost model:
  One base ticket per draw at the game's base wager. Add-ons (Extra!,
  Power Play, Megaplier, Fireball) are NOT modelled — the UI must
  disclose this.

Play types (explicit):
  - Lotto Texas       6-of-54 main only, $1
  - Mega Millions     5-of-70 + Mega Ball, $5
  - Powerball         5-of-69 + Powerball,   $2
  - Cash Five         5-of-35, $1
  - Texas Two Step    4-of-35 + Bonus Ball,  $1
  - All or Nothing    12-of-24 (symmetric),  $2
  - Pick 3            $1 Straight, exact-order match
  - Daily 4           $1 Straight, exact-order match

Prize amounts come from checker.check_ticket; jackpot / pari-mutuel tiers
resolve to None (the log shows "Jackpot / varies" rather than a made-up
number).

Cached per game to `data/purchase_cache/<game>_<sig>.json` keyed on the
CSV mtime signature so cron refreshes invalidate cleanly.
"""
from __future__ import annotations
import hashlib
import json
import os
from collections import Counter
from datetime import date
from typing import Dict, List, Optional
from games import GAMES, GameConfig
from loader import load_draws_full
from strategies import s1_from_counter, s1_from_position_counters
from checker import check_ticket

CACHE_DIR = "data/purchase_cache"
BURN_IN = 50

# The formal "experiment start" — the date the Purchases tab went live
# and from which the going-forward simulated tracking begins. Filter the
# full walk-forward log to this cutoff for the "since experiment started"
# view. Everything before this cutoff is the "all-time hypothetical" view.
EXPERIMENT_START = date(2026, 7, 10)

# Per-game display label + numeric cost per single ticket. Numeric cost
# overrides `ticket_cost_low` for digit games where the base wager we
# simulate is $1 (Straight), not the $0.50 game minimum.
PLAY_TYPE_LABEL: Dict[str, str] = {
    "Lotto Texas":    "6-of-54 (main only, no Extra!)",
    "Mega Millions":  "5-of-70 + Mega Ball",
    "Powerball":      "5-of-69 + Powerball",
    "Cash Five":      "5-of-35",
    "Texas Two Step": "4-of-35 + Bonus Ball",
    "All or Nothing": "12-of-24 (symmetric — win at all-12 or all-0)",
    "Pick 3":         "$1 Straight (exact-order match)",
    "Daily 4":        "$1 Straight (exact-order match)",
}
COST_PER_TICKET: Dict[str, float] = {
    "Lotto Texas":    1.0,
    "Mega Millions":  5.0,
    "Powerball":      2.0,
    "Cash Five":      1.0,
    "Texas Two Step": 1.0,
    "All or Nothing": 2.0,
    "Pick 3":         1.0,
    "Daily 4":        1.0,
}


def _sig(game: GameConfig) -> str:
    parts = tuple(os.path.getmtime(p) if os.path.exists(p) else 0.0
                  for p in game.csv_paths)
    return hashlib.sha1(str(parts).encode()).hexdigest()[:12]


def _cache_path(game_name: str) -> str:
    safe = game_name.replace(" ", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{_sig(GAMES[game_name])}.json")


def _simulate_kn(game: GameConfig, era_full: List[dict],
                 bonus_by_date: Optional[Dict] = None) -> List[dict]:
    """Walk-forward S1 for a k-of-N game. bonus_by_date maps
    (date, slot) -> bonus_int for the game's era (None for games without
    a bonus pool). Returns one record per scored draw."""
    K, N = game.k_main, game.n_main
    counter: Counter = Counter()
    # Track bonus counts for walk-forward top-1 bonus.
    bonus_counter: Counter = Counter() if game.bonus_n else None
    log: List[dict] = []

    for t, row in enumerate(era_full):
        dt = row["date"]
        slot = row["slot"]
        draw_main = row["main"]
        draw_bonus = row["bonus"]

        if t >= BURN_IN:
            s1 = s1_from_counter(counter, K, N)
            picked_bonus = None
            if game.bonus_n and len(bonus_counter) > 0:
                ordered = sorted(range(1, game.bonus_n + 1),
                                 key=lambda b: (-bonus_counter.get(b, 0), b))
                picked_bonus = ordered[0]

            result = check_ticket(
                game.name,
                user_main=set(s1),
                draw_main=draw_main,
                user_bonus=picked_bonus,
                draw_bonus=draw_bonus,
            )
            log.append({
                "date": dt.isoformat(),
                "slot": slot,
                "s1": list(s1),
                "user_bonus": picked_bonus,
                "draw_main": list(draw_main),
                "draw_bonus": draw_bonus,
                "matches": result.get("matches"),
                "bonus_match": result.get("bonus_match", False),
                "tier": result["tier"],
                "prize": result["prize"],
                "cost": COST_PER_TICKET[game.name],
            })

        counter.update(draw_main)
        if game.bonus_n and draw_bonus is not None:
            bonus_counter[draw_bonus] += 1

    return log


def _simulate_digit(game: GameConfig, era_full: List[dict]) -> List[dict]:
    """Walk-forward per-position S1 for a digit game (Pick 3 / Daily 4).
    Play type: $1 Straight."""
    K, N = game.k_main, game.n_main
    per_pos = [Counter() for _ in range(K)]
    log: List[dict] = []

    for t, row in enumerate(era_full):
        dt = row["date"]
        slot = row["slot"]
        draw_main = row["main"]

        if t >= BURN_IN:
            s1 = s1_from_position_counters(per_pos, K, N)
            result = check_ticket(
                game.name, user_main=tuple(s1),
                draw_main=draw_main,
                play_type="Straight",
                dollar_play=1.0,
            )
            log.append({
                "date": dt.isoformat(),
                "slot": slot,
                "s1": list(s1),
                "user_bonus": None,
                "draw_main": list(draw_main),
                "draw_bonus": None,
                "matches": None,  # digit games use exact/positional
                "bonus_match": False,
                "tier": result["tier"],
                "prize": result["prize"],
                "cost": COST_PER_TICKET[game.name],
            })

        for i, d in enumerate(draw_main):
            if i < K:
                per_pos[i][d] += 1

    return log


def simulate_game(game_name: str) -> List[dict]:
    """Return the walk-forward purchase log for one game. Disk-cached."""
    cache_p = _cache_path(game_name)
    if os.path.exists(cache_p):
        try:
            with open(cache_p) as f:
                return json.load(f)
        except Exception:
            pass  # fall through and recompute

    game = GAMES[game_name]
    era_full = [r for r in load_draws_full(game) if r["date"] >= game.era_start]

    if game.game_type == "digit":
        log = _simulate_digit(game, era_full)
    else:
        log = _simulate_kn(game, era_full)

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_p, "w") as f:
        json.dump(log, f)
    return log


def summarize(records: List[dict]) -> Dict:
    """Roll up a filtered list of purchase records into summary metrics."""
    n = len(records)
    total_spent = sum(r["cost"] for r in records)
    # For jackpot/pari-mutuel tiers, prize is None — count separately
    fixed_wins = [r for r in records
                  if isinstance(r["prize"], (int, float)) and r["prize"] > 0]
    variable_wins = [r for r in records if r["prize"] is None]
    total_winnings = sum(r["prize"] for r in fixed_wins)
    best_win = max(fixed_wins, key=lambda r: r["prize"], default=None)
    return {
        "n_tickets": n,
        "total_spent": total_spent,
        "total_winnings_fixed": total_winnings,
        "n_fixed_wins": len(fixed_wins),
        "n_variable_wins": len(variable_wins),   # jackpot/pari-mutuel hits
        "net": total_winnings - total_spent,
        "hit_rate": (len(fixed_wins) + len(variable_wins)) / n if n else 0.0,
        "best_win": best_win,
    }
