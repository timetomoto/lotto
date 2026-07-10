"""Candidate sequence strategies for both game types.

Single source of truth for S1 selection lives in `s1_from_counter` and
`s1_from_position_counters`. Both production (`walk_forward_backtest`) and
the Monte Carlo null harness (`mc_null.mc_walk_forward_null`) must call
these so tie-breaking is identical everywhere. If tie-breaking diverges,
the MC null is calibrated against the wrong reference and the reported
z-scores no longer correspond to the numbers in the UI.

k-of-N games:
- S1 most-frequent: top-K distinct balls by historical count
- S4 least-frequent: bottom-K distinct balls
- S2 PRNG / S3 QRNG: uniform K-of-N sample without replacement

Digit games (positional, with replacement):
- S1 per-position most-frequent digit
- S4 per-position least-frequent digit
- S2/S3: uniform digits per position
"""
from collections import Counter
from typing import List, Tuple, Sequence
import numpy as np
from games import GameConfig
from loader import Draw

# ---- Canonical S1 selection helpers (used by both production and MC) ------

def s1_from_counter(counter: Counter, K: int, N: int) -> Tuple[int, ...]:
    """Top-K balls from a k-of-N frequency counter. Ties broken by lower
    ball number first. Balls are 1-indexed."""
    ordered = sorted(range(1, N + 1), key=lambda b: (-counter.get(b, 0), b))
    return tuple(sorted(ordered[:K]))

def top_bonus_by_frequency(game: GameConfig, bonus_values,
                           k: int = 1) -> list:
    """Return the top-k most-frequent bonus-ball values (ranked, no ties).
    Empty list if the game has no bonus pool. Tie-break: lower value wins,
    consistent with `s1_from_counter`."""
    if not game.bonus_n or not bonus_values:
        return []
    c = Counter(bonus_values)
    ordered = sorted(range(1, game.bonus_n + 1),
                     key=lambda b: (-c.get(b, 0), b))
    return ordered[:k]

def most_frequent_bonus(game: GameConfig, bonus_values) -> "int | None":
    """Most-frequent bonus-ball value; None if game has no bonus pool.
    Thin wrapper for callers that only need the top value."""
    top = top_bonus_by_frequency(game, bonus_values, k=1)
    return top[0] if top else None

def s1_from_position_counters(counters: Sequence[Counter], K: int, N: int
                              ) -> Tuple[int, ...]:
    """Argmax digit at each position for a K-position digit game.
    Ties broken by lower digit first (matches production convention)."""
    return tuple(
        max(range(N), key=lambda d: (counters[i].get(d, 0), -d))
        for i in range(K)
    )

# ---- shared helpers --------------------------------------------------------

def frequency_counter(draws: List[Draw]) -> Counter:
    """Ball-frequency counter across the whole draw (both game types)."""
    c: Counter = Counter()
    for _, nums in draws:
        c.update(nums)
    return c

def per_position_counters(draws: List[Draw], k: int) -> List[Counter]:
    """For digit games: one Counter per position."""
    counters = [Counter() for _ in range(k)]
    for _, nums in draws:
        for i in range(k):
            if i < len(nums):
                counters[i][nums[i]] += 1
    return counters

# ---- k-of-N strategies -----------------------------------------------------

def s1_most_frequent_kn(draws: List[Draw], game: GameConfig) -> Tuple[int, ...]:
    return s1_from_counter(frequency_counter(draws), game.k_main, game.n_main)

def s4_least_frequent_kn(draws: List[Draw], game: GameConfig) -> Tuple[int, ...]:
    c = frequency_counter(draws)
    ordered = sorted(range(1, game.n_main + 1), key=lambda b: (c.get(b, 0), b))
    return tuple(sorted(ordered[:game.k_main]))

def s2_prng_kn(game: GameConfig, seed: int) -> Tuple[int, ...]:
    rng = np.random.default_rng(seed)
    picks = rng.choice(game.n_main, size=game.k_main, replace=False) + 1
    return tuple(sorted(int(x) for x in picks))

def s3_qrng_kn(bytestream: bytes, game: GameConfig) -> Tuple[int, ...]:
    """Fisher-Yates from QRNG bytes with rejection sampling to avoid modulo bias."""
    pool = list(range(1, game.n_main + 1))
    picks: List[int] = []
    idx = 0
    while len(picks) < game.k_main:
        if idx >= len(bytestream):
            raise ValueError("QRNG stream exhausted before pick complete")
        b = bytestream[idx]; idx += 1
        limit = (256 // len(pool)) * len(pool)
        if b >= limit:
            continue
        picks.append(pool.pop(b % len(pool)))
    return tuple(sorted(picks))

# ---- digit-game strategies -------------------------------------------------

def s1_most_frequent_digit(draws: List[Draw], game: GameConfig) -> Tuple[int, ...]:
    """Per-position most-frequent digit."""
    return s1_from_position_counters(
        per_position_counters(draws, game.k_main), game.k_main, game.n_main
    )

def s4_least_frequent_digit(draws: List[Draw], game: GameConfig) -> Tuple[int, ...]:
    per_pos = per_position_counters(draws, game.k_main)
    picks = []
    for c in per_pos:
        worst = min(range(game.n_main), key=lambda d: (c.get(d, 0), d))
        picks.append(worst)
    return tuple(picks)

def s2_prng_digit(game: GameConfig, seed: int) -> Tuple[int, ...]:
    rng = np.random.default_rng(seed)
    return tuple(int(x) for x in rng.integers(0, game.n_main, size=game.k_main))

def s3_qrng_digit(bytestream: bytes, game: GameConfig) -> Tuple[int, ...]:
    picks = []
    idx = 0
    limit = (256 // game.n_main) * game.n_main
    while len(picks) < game.k_main:
        if idx >= len(bytestream):
            raise ValueError("QRNG stream exhausted before pick complete")
        b = bytestream[idx]; idx += 1
        if b >= limit:
            continue
        picks.append(b % game.n_main)
    return tuple(picks)

# ---- dispatchers -----------------------------------------------------------

def s1_most_frequent(draws, game):
    return s1_most_frequent_kn(draws, game) if game.game_type == "kn" \
        else s1_most_frequent_digit(draws, game)

def s4_least_frequent(draws, game):
    return s4_least_frequent_kn(draws, game) if game.game_type == "kn" \
        else s4_least_frequent_digit(draws, game)

def s2_prng(game, seed):
    return s2_prng_kn(game, seed) if game.game_type == "kn" \
        else s2_prng_digit(game, seed)

def s3_qrng(bytestream, game):
    return s3_qrng_kn(bytestream, game) if game.game_type == "kn" \
        else s3_qrng_digit(bytestream, game)
