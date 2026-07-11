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

# ---- Collision-avoidance (the honest player-side edge) --------------

# Empirically documented player-picking biases across state lotteries:
#   - Balls 1-31 ("birthday range") are dramatically over-picked
#   - Specific numbers commonly considered lucky get extra love
#   - Multiples of 5 attract round-number bias
# Player behavior isn't statistical prediction — it's game theory:
# picking unpopular numbers doesn't change P(win), it changes E[payout | win]
# for games with jackpots that split among multiple winners.

LUCKY_NUMBERS = {7, 11, 13, 17, 21, 23, 27}  # documented popularity spikes

def collision_risk_score(ball: int) -> float:
    """Higher = more commonly picked by other players (bad for prize-splitting).
    Roughly calibrated against published lottery-selection studies."""
    score = 0.0
    if 1 <= ball <= 31:
        score += 1.0            # birthday-range bias — the biggest effect
    if ball in LUCKY_NUMBERS:
        score += 0.5            # lucky-number extra
    if ball % 5 == 0 and 1 <= ball <= 50:
        score += 0.2            # round-number bias
    return score

def anti_collision_sequence(game: GameConfig, draws=None) -> tuple:
    """Return K numbers optimized to be UNPOPULAR — least likely to be
    picked by other players — so that if the ticket wins, it's less
    likely to share the jackpot.

    Blends S1 "prediction" (most-frequent historically) with collision
    avoidance so every game produces a *distinct* strategy tuned to its
    own history — no more identical 32-33-34-… tickets across games.

    Ranking priority (per ball):
      1. Player-behavior risk (birthday-range / lucky-number / round-5)
         — hard filter against the strongest documented biases.
      2. Historical draw frequency (MOST-frequent first, S1-style) —
         within the low-collision pool, favor balls that have hit more
         often over the full era.
      3. Spread constraint: reject picks adjacent (gap < 2) to already
         chosen balls, discouraging clumped consecutive tickets.
      4. Higher ball number as final tie-break (rare > common by pool
         convention).

    Explicitly NOT a prediction. Win probability is identical to any
    other single ticket at 1 / C(N, K). This is only about *conditional*
    expected payout given a win, for games with rolling shared jackpots.
    """
    K, N = game.k_main, game.n_main
    freq: Counter = Counter()
    if draws is not None:
        for _, nums in draws:
            freq.update(nums)

    candidates = sorted(
        range(1, N + 1),
        key=lambda b: (
            collision_risk_score(b),
            -freq.get(b, 0),       # MOST historically-drawn first (S1 blend)
            -b,                    # higher ball wins final tie-break
        ),
    )
    # Greedy select K, preferring a min-gap-of-2 spread — but only when
    # rejecting the neighbor still leaves enough SAME-collision-tier
    # candidates to fill the ticket. Otherwise take the neighbor rather
    # than dropping into the next (worse) collision tier. This is what
    # kept Texas Two Step from falling back to birthday-range balls just
    # because 34 was adjacent to 33.
    picks: list = []
    remaining = list(candidates)
    while len(picks) < K and remaining:
        b = remaining.pop(0)
        if any(abs(b - p) < 2 for p in picks):
            tier = collision_risk_score(b)
            same_tier_left = sum(
                1 for c in remaining
                if collision_risk_score(c) == tier
                and all(abs(c - p) >= 2 for p in picks)
            )
            need = K - len(picks)
            if same_tier_left >= need:
                # Enough same-tier non-adjacent options — skip this one.
                continue
        picks.append(b)
    return tuple(sorted(picks))

# Documented digit-game player biases: 7 most-picked, 3 second, 5 popular,
# 1/2 birthday-days. 0/8/9 relatively unpopular. Applied per-position for
# digit games as the collision-avoidance variant. Higher score = more
# commonly picked (bad for prize-splitting).
DIGIT_POPULARITY = {7: 1.5, 3: 1.2, 5: 1.0, 1: 0.8, 2: 0.8,
                    4: 0.4, 6: 0.4, 9: 0.2, 8: 0.1, 0: 0.0}

def digit_anti_collision(counters: Sequence[Counter], K: int, N: int
                         ) -> Tuple[int, ...]:
    """Per-position pick minimizing (player popularity, -historical freq).
    For Pick 3 / Daily 4. Mirrors the k-of-N anti_collision_sequence blend
    of avoidance + S1-style prediction."""
    return tuple(
        min(range(N),
            key=lambda d: (DIGIT_POPULARITY.get(d, 0.5),
                           -counters[i].get(d, 0),
                           -d))
        for i in range(K)
    )

def anti_collision_bonus(game: GameConfig) -> "int | None":
    """Anti-collision pick for the bonus pool.
    Within a pool that's usually fully inside the birthday range (1-25,
    1-26), all values carry the birthday penalty equally, so we pick the
    HIGHEST non-lucky non-multiple-of-5 value — high numbers are picked
    less often than mid-range picks even inside the birthday window.
    None if the game has no bonus pool."""
    if not game.bonus_n:
        return None
    for b in range(game.bonus_n, 0, -1):
        if b in LUCKY_NUMBERS: continue
        if b % 5 == 0: continue
        return b
    return game.bonus_n

def birthday_ball_count(seq) -> int:
    """How many of the K balls fall in the 1-31 'birthday range'."""
    return sum(1 for b in seq if 1 <= b <= 31)

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
