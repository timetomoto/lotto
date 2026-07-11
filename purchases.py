"""Walk-forward simulation of buying one ticket per draw under three
strategies. The "player" is assumed to have bought a ticket at each
historical draw t (past a 50-draw burn-in) using one of:

  s1        — top-K most-frequent balls (or per-position most-frequent
              digits) computed from draws BEFORE t. Matches what the
              app's Overview card shows at that moment.
  s2        — a fresh PRNG ticket, seeded deterministically per (game,
              date, slot) so the historical log is stable across runs.
  strategy  — collision-avoidance ticket blending S1-style prediction
              with anti-popular-number filtering; for k-of-N games this
              uses `anti_collision_sequence` with the prior-draw history.

Bonus ball follows the main strategy: s1 → most-frequent bonus so far,
s2 → deterministic PRNG bonus, strategy → `anti_collision_bonus`.

Cost model: one base ticket per draw at the game's base wager. Add-ons
(Extra!, Power Play, Megaplier, Fireball) are NOT modelled.

Play types:
  - Lotto Texas       6-of-54 main only, $1
  - Mega Millions     5-of-70 + Mega Ball, $5
  - Powerball         5-of-69 + Powerball,   $2
  - Cash Five         5-of-35, $1
  - Texas Two Step    4-of-35 + Bonus Ball,  $1
  - All or Nothing    12-of-24 (symmetric),  $2
  - Pick 3            $1 Straight, exact-order match
  - Daily 4           $1 Straight, exact-order match

Cached per (game, strategy) to `data/purchase_cache/<game>_<strategy>_<sig>.json`
keyed on the CSV mtime signature so cron refreshes invalidate cleanly.
"""
from __future__ import annotations
import hashlib
import json
import os
from collections import Counter
from datetime import date
from typing import Dict, List, Optional
import numpy as np
from games import GAMES, GameConfig
from loader import load_draws_full
from strategies import (
    s1_from_counter, s1_from_position_counters, s2_prng,
    anti_collision_sequence, anti_collision_bonus,
    digit_anti_collision,
)
from checker import check_ticket

CACHE_DIR = "data/purchase_cache"
BURN_IN = 50

# Iteration order drives the Purchases page: head-to-head column order,
# per-strategy sub-tab order, and any cache-warming loop. Strategy first
# because it's the primary anti-collision recommendation; S1 and S2 sit
# beside it for reference.
STRATEGIES = ("strategy", "s1", "s2")
STRATEGY_LABEL = {
    "s1":       "S1 (most-frequent)",
    "s2":       "S2 (random)",
    "strategy": "🎯 Strategy (anti-collision)",
}
STRATEGY_TAGLINE = {
    "s1":       "Top-K historically most-frequent balls, walk-forward.",
    "s2":       "Fresh PRNG ticket per draw, deterministic seed per (game, date, slot).",
    "strategy": "Collision-avoidance blend of S1 prediction + anti-popular-number filter.",
}

# The formal "experiment start" — the date the Purchases tab went live
# and from which the going-forward simulated tracking begins. Filter the
# full walk-forward log to this cutoff for the "since experiment started"
# view. Everything before this cutoff is the "all-time hypothetical" view.
EXPERIMENT_START = date(2026, 7, 10)

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


def _cache_path(game_name: str, strategy: str) -> str:
    safe = game_name.replace(" ", "_")
    return os.path.join(CACHE_DIR,
                        f"{safe}_{strategy}_{_sig(GAMES[game_name])}.json")


def _draw_seed(game_name: str, dt: date, slot: Optional[str]) -> int:
    """Stable per-draw seed for S2, so the same historical draw always
    yields the same S2 ticket."""
    key = f"{game_name}|{dt.isoformat()}|{slot or ''}"
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16)


def _s2_bonus(game: GameConfig, seed: int) -> int:
    rng = np.random.default_rng(seed ^ 0xA5A5A5A5)
    return int(rng.integers(1, game.bonus_n + 1))


def _simulate_kn(game: GameConfig, era_full: List[dict],
                 strategy: str) -> List[dict]:
    """Walk-forward k-of-N simulation for one strategy. Returns one record
    per scored draw."""
    K, N = game.k_main, game.n_main
    counter: Counter = Counter()
    bonus_counter: Counter = Counter() if game.bonus_n else None
    prior_draws: List = []            # for strategy (anti-collision) picks
    log: List[dict] = []

    for t, row in enumerate(era_full):
        dt = row["date"]
        slot = row["slot"]
        draw_main = row["main"]
        draw_bonus = row["bonus"]

        if t >= BURN_IN:
            # ---- Pick main ticket per-strategy ----
            if strategy == "s1":
                ticket = s1_from_counter(counter, K, N)
            elif strategy == "s2":
                seed = _draw_seed(game.name, dt, slot)
                ticket = s2_prng(game, seed)
            elif strategy == "strategy":
                ticket = anti_collision_sequence(game, draws=prior_draws)
            else:
                raise ValueError(f"unknown strategy {strategy!r}")

            # ---- Pick bonus ball per-strategy ----
            picked_bonus: Optional[int] = None
            if game.bonus_n:
                if strategy == "s1":
                    if len(bonus_counter) > 0:
                        ordered = sorted(range(1, game.bonus_n + 1),
                                         key=lambda b: (-bonus_counter.get(b, 0), b))
                        picked_bonus = ordered[0]
                elif strategy == "s2":
                    picked_bonus = _s2_bonus(game, _draw_seed(game.name, dt, slot))
                elif strategy == "strategy":
                    picked_bonus = anti_collision_bonus(game)

            result = check_ticket(
                game.name,
                user_main=set(ticket),
                draw_main=draw_main,
                user_bonus=picked_bonus,
                draw_bonus=draw_bonus,
            )
            log.append({
                "date": dt.isoformat(),
                "slot": slot,
                "s1": list(ticket),          # kept as "s1" key for UI compat
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
        prior_draws.append((dt, draw_main))

    return log


def _simulate_digit(game: GameConfig, era_full: List[dict],
                    strategy: str) -> List[dict]:
    """Walk-forward digit-game simulation. Play type: $1 Straight."""
    K, N = game.k_main, game.n_main
    per_pos = [Counter() for _ in range(K)]
    log: List[dict] = []

    for t, row in enumerate(era_full):
        dt = row["date"]
        slot = row["slot"]
        draw_main = row["main"]

        if t >= BURN_IN:
            if strategy == "s1":
                ticket = s1_from_position_counters(per_pos, K, N)
            elif strategy == "s2":
                seed = _draw_seed(game.name, dt, slot)
                ticket = s2_prng(game, seed)
            elif strategy == "strategy":
                ticket = digit_anti_collision(per_pos, K, N)
            else:
                raise ValueError(f"unknown strategy {strategy!r}")

            result = check_ticket(
                game.name, user_main=tuple(ticket),
                draw_main=draw_main,
                play_type="Straight",
                dollar_play=1.0,
            )
            log.append({
                "date": dt.isoformat(),
                "slot": slot,
                "s1": list(ticket),          # kept as "s1" key for UI compat
                "user_bonus": None,
                "draw_main": list(draw_main),
                "draw_bonus": None,
                "matches": None,
                "bonus_match": False,
                "tier": result["tier"],
                "prize": result["prize"],
                "cost": COST_PER_TICKET[game.name],
            })

        for i, d in enumerate(draw_main):
            if i < K:
                per_pos[i][d] += 1

    return log


def simulate_game(game_name: str, strategy: str = "s1") -> List[dict]:
    """Return the walk-forward purchase log for one game under one strategy.
    Disk-cached per (game, strategy). Strategy must be one of STRATEGIES."""
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}, got {strategy!r}")

    cache_p = _cache_path(game_name, strategy)
    if os.path.exists(cache_p):
        try:
            with open(cache_p) as f:
                return json.load(f)
        except Exception:
            pass  # fall through and recompute

    game = GAMES[game_name]
    era_full = [r for r in load_draws_full(game) if r["date"] >= game.era_start]

    if game.game_type == "digit":
        log = _simulate_digit(game, era_full, strategy)
    else:
        log = _simulate_kn(game, era_full, strategy)

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_p, "w") as f:
        json.dump(log, f)
    return log


def summarize(records: List[dict]) -> Dict:
    """Roll up a filtered list of purchase records into summary metrics."""
    n = len(records)
    total_spent = sum(r["cost"] for r in records)
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
        "n_variable_wins": len(variable_wins),
        "net": total_winnings - total_spent,
        "hit_rate": (len(fixed_wins) + len(variable_wins)) / n if n else 0.0,
        "best_win": best_win,
    }
