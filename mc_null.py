"""Monte Carlo null distributions for the randomness audits.

Why this exists: for a fair k-of-N draw, each ball's count is Binomial(D, K/N)
and pairs of ball-counts are negatively correlated within a draw (a ball being
drawn excludes others). The chi-square statistic
    χ² = Σ (O_i − E)² / E
has expected value **N − K** under this null, not N − 1. Comparing it against
the textbook χ²(df = N − 1) distribution runs conservative — most severely
when K/N is large (e.g., All or Nothing K/N = 0.5 → E[χ²] = 12 vs the
textbook reference of 23). This module builds the correct empirical null by
simulating fair histories and computing the same statistic on each.

The digit-game per-position chi-square does NOT need this correction — each
position is genuinely independent under H₀ and the textbook df = N − 1
distribution is exact.

Caches empirical nulls to `data/mc_cache/{game_key}_{tag}_{n_sim}_{seed}.npz`
keyed on the era CSV mtime signature so cron writes invalidate.
"""
from __future__ import annotations
import hashlib
import os
import numpy as np
from typing import Dict
from games import GameConfig

CACHE_DIR = "data/mc_cache"

# ------------------------------------------------------------------
# Fair-history simulation
# ------------------------------------------------------------------

def simulate_kn_counts(D: int, K: int, N: int, n_sim: int,
                       rng: np.random.Generator) -> np.ndarray:
    """Return an (n_sim, N) int array where each row is the per-ball count
    from a simulated fair K-of-N history of D draws.

    Vectorized: for each draw we generate N uniform values and take the
    K smallest indices. This is O(D · N) per simulation, cheap enough to
    run tens of thousands of times.
    """
    out = np.zeros((n_sim, N), dtype=np.int64)
    for i in range(n_sim):
        r = rng.random((D, N))
        top_k = np.argpartition(r, K - 1, axis=1)[:, :K]
        counts = np.bincount(top_k.ravel(), minlength=N)
        out[i] = counts
    return out

# ------------------------------------------------------------------
# A1 — Chi-square null for k-of-N frequency audit
# ------------------------------------------------------------------

def _cache_key(game_key: str, tag: str, n_sim: int, seed: int,
               sig: tuple) -> str:
    h = hashlib.sha1(
        f"{game_key}|{tag}|{n_sim}|{seed}|{sig}".encode()
    ).hexdigest()[:12]
    safe_game = game_key.replace(" ", "_")
    return os.path.join(CACHE_DIR, f"{safe_game}_{tag}_n{n_sim}_s{seed}_{h}.npz")

def _era_signature_kn(game: GameConfig) -> tuple:
    return tuple(os.path.getmtime(p) if os.path.exists(p) else 0.0
                 for p in game.csv_paths)

def mc_chi_square_null_kn(game: GameConfig, D: int, n_sim: int = 10_000,
                          seed: int = 0) -> np.ndarray:
    """Return an array of n_sim chi-square statistics computed on simulated
    fair K-of-N histories of length D. Cached on disk."""
    sig = _era_signature_kn(game)
    cache_path = _cache_key(game.name, "chi2", n_sim, seed, sig + (D,))
    if os.path.exists(cache_path):
        return np.load(cache_path)["chi2"]

    rng = np.random.default_rng(seed)
    K, N = game.k_main, game.n_main
    counts = simulate_kn_counts(D, K, N, n_sim, rng)
    exp = D * K / N
    chi2 = np.sum((counts - exp) ** 2 / exp, axis=1)

    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez_compressed(cache_path, chi2=chi2)
    return chi2

# ------------------------------------------------------------------
# A2 — Walk-forward null (calls the real walk_forward_backtest so
# tie-breaking is guaranteed identical to production).
# ------------------------------------------------------------------

def _simulate_history_as_draws(D: int, game: GameConfig,
                               rng: np.random.Generator):
    """Return a list of (fake_date, tuple-of-balls) that walk_forward_backtest
    can consume. balls are 1-indexed for kn, 0-indexed for digit games."""
    from datetime import date, timedelta
    base = date(2000, 1, 1)
    if game.game_type == "kn":
        r = rng.random((D, game.n_main))
        idx = np.argpartition(r, game.k_main - 1, axis=1)[:, :game.k_main] + 1
        return [(base + timedelta(days=t), tuple(int(x) for x in idx[t]))
                for t in range(D)]
    else:
        digits = rng.integers(0, game.n_main, size=(D, game.k_main))
        return [(base + timedelta(days=t), tuple(int(x) for x in digits[t]))
                for t in range(D)]

def mc_walk_forward_null(game: GameConfig, D: int, burn_in: int = 50,
                         n_sim: int = 200, seed: int = 0) -> Dict:
    """Empirical null distribution for the walk-forward backtest.

    For each of n_sim simulated fair histories of length D, run the same
    walk_forward_backtest as production and record the aggregate match
    distribution. Because both paths call `strategies.s1_from_counter` /
    `s1_from_position_counters`, tie-breaking is identical by construction.

    Returns:
        {
            "counts_3plus": array of shape (n_sim,) with the per-sim total
                of matches >= 3 (for kn; exact-match count for digit games),
            "obs_counts_all": (n_sim, K+1) match-count histograms,
            "n_scored": D - burn_in,
            "burn_in": burn_in,
            "n_sim": n_sim,
        }
    Cached on disk under data/mc_cache/.
    """
    from stats_tests import walk_forward_backtest  # avoid circular import at module load
    sig = _era_signature_kn(game)
    cache_path = _cache_key(game.name, "wf", n_sim, seed,
                            sig + (D, burn_in))
    if os.path.exists(cache_path):
        z = np.load(cache_path)
        return {
            "counts_3plus": z["counts_3plus"],
            "obs_counts_all": z["obs_counts_all"],
            "n_scored": int(z["n_scored"]),
            "burn_in": burn_in, "n_sim": n_sim,
        }

    rng = np.random.default_rng(seed)
    K = game.k_main
    counts_3plus = np.zeros(n_sim, dtype=np.int64)
    obs_counts_all = np.zeros((n_sim, K + 1), dtype=np.int64)
    for i in range(n_sim):
        sim_draws = _simulate_history_as_draws(D, game, rng)
        r = walk_forward_backtest(sim_draws, game, burn_in=burn_in)
        obs_counts_all[i] = r["obs_counts"]
        if game.game_type == "kn":
            counts_3plus[i] = sum(r["obs_counts"][3:])
        else:
            counts_3plus[i] = r["obs_counts"][game.k_main]
    n_scored = D - burn_in

    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez_compressed(
        cache_path,
        counts_3plus=counts_3plus,
        obs_counts_all=obs_counts_all,
        n_scored=np.int64(n_scored),
    )
    return {
        "counts_3plus": counts_3plus,
        "obs_counts_all": obs_counts_all,
        "n_scored": n_scored,
        "burn_in": burn_in, "n_sim": n_sim,
    }

# ------------------------------------------------------------------
# B1 — Serial-dependence MC null (Ljung-Box aggregation + runs test)
# ------------------------------------------------------------------

def mc_serial_dependence_null(game: GameConfig, D: int, n_sim: int = 100,
                              seed: int = 0, lags: int = 10) -> Dict:
    """Empirical null for the serial-dependence aggregation statistics.

    For each simulated fair history of length D, compute:
      - max_ljung_box: max LB statistic across the ball-indicator series
      - prop_lb_below_05: fraction of ball series with LB p < 0.05
      - runs_test_p: draw-sum runs test p-value
    Return the empirical distributions of these under H₀.

    Under H₀ the per-ball series are NOT independent (within-draw negative
    correlation), so the theoretical uniform-p reference is invalid.
    Calibrating with MC avoids that.
    """
    from stats_tests import (ljung_box_per_ball, runs_test_draw_sums)
    sig = _era_signature_kn(game)
    cache_path = _cache_key(game.name, "serial", n_sim, seed,
                            sig + (D, lags))
    if os.path.exists(cache_path):
        z = np.load(cache_path)
        return {
            "max_ljung_box": z["max_ljung_box"],
            "prop_lb_below_05": z["prop_lb_below_05"],
            "runs_test_p": z["runs_test_p"],
            "n_sim": n_sim,
        }

    rng = np.random.default_rng(seed)
    max_lb = np.zeros(n_sim)
    prop_lb = np.zeros(n_sim)
    runs_p = np.zeros(n_sim)
    for i in range(n_sim):
        sim_draws = _simulate_history_as_draws(D, game, rng)
        lb = ljung_box_per_ball(sim_draws, game, lags=lags)
        rt = runs_test_draw_sums(sim_draws, game)
        max_lb[i] = lb["max_stat"]
        prop_lb[i] = lb["prop_below_05"]
        runs_p[i] = rt["p"]

    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez_compressed(cache_path,
                        max_ljung_box=max_lb,
                        prop_lb_below_05=prop_lb,
                        runs_test_p=runs_p)
    return {
        "max_ljung_box": max_lb,
        "prop_lb_below_05": prop_lb,
        "runs_test_p": runs_p,
        "n_sim": n_sim,
    }

# ------------------------------------------------------------------
# B3 — Gap-test MC null (kn games only)
# ------------------------------------------------------------------

def mc_gap_test_null(game: GameConfig, D: int, n_sim: int = 100,
                     seed: int = 0) -> Dict:
    """Empirical null for the gap-test aggregation statistics (kn games).
    Returns arrays of max χ² and prop_below_05 across n_sim fair histories."""
    from stats_tests import gap_test_aggregate
    if game.game_type != "kn":
        return {"applicable": False}
    sig = _era_signature_kn(game)
    cache_path = _cache_key(game.name, "gap", n_sim, seed, sig + (D,))
    if os.path.exists(cache_path):
        z = np.load(cache_path)
        return {
            "max_chi2": z["max_chi2"],
            "prop_below_05": z["prop_below_05"],
            "n_sim": n_sim, "applicable": True,
        }
    rng = np.random.default_rng(seed)
    max_chi2 = np.zeros(n_sim)
    prop = np.zeros(n_sim)
    for i in range(n_sim):
        sim_draws = _simulate_history_as_draws(D, game, rng)
        r = gap_test_aggregate(sim_draws, game)
        max_chi2[i] = r["max_stat"]
        prop[i] = r["prop_below_05"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez_compressed(cache_path, max_chi2=max_chi2, prop_below_05=prop)
    return {"max_chi2": max_chi2, "prop_below_05": prop,
            "n_sim": n_sim, "applicable": True}

# ------------------------------------------------------------------
# B2 — Pairwise co-occurrence MC null (kn games only)
# ------------------------------------------------------------------

def mc_pair_cooccurrence_null(game: GameConfig, D: int, n_sim: int = 200,
                              seed: int = 0) -> Dict:
    """Empirical null for max |z| and χ²-like pair-count aggregations."""
    from stats_tests import pair_cooccurrence_aggregate
    if game.game_type != "kn":
        return {"applicable": False}
    sig = _era_signature_kn(game)
    cache_path = _cache_key(game.name, "pair", n_sim, seed, sig + (D,))
    if os.path.exists(cache_path):
        z = np.load(cache_path)
        return {"max_z": z["max_z"], "chi2_like": z["chi2_like"],
                "n_sim": n_sim, "applicable": True}
    rng = np.random.default_rng(seed)
    max_z = np.zeros(n_sim)
    chi2_like = np.zeros(n_sim)
    for i in range(n_sim):
        sim_draws = _simulate_history_as_draws(D, game, rng)
        r = pair_cooccurrence_aggregate(sim_draws, game)
        max_z[i] = r["max_z"]
        chi2_like[i] = r["chi2_like"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez_compressed(cache_path, max_z=max_z, chi2_like=chi2_like)
    return {"max_z": max_z, "chi2_like": chi2_like,
            "n_sim": n_sim, "applicable": True}

# ------------------------------------------------------------------
# B4 — CUSUM drift MC null (kn games only)
# ------------------------------------------------------------------

def mc_cusum_drift_null(game: GameConfig, D: int, n_sim: int = 200,
                        seed: int = 0) -> Dict:
    """Empirical null distribution of max cumulative excursion."""
    from stats_tests import cusum_drift_aggregate
    if game.game_type != "kn":
        return {"applicable": False}
    sig = _era_signature_kn(game)
    cache_path = _cache_key(game.name, "cusum", n_sim, seed, sig + (D,))
    if os.path.exists(cache_path):
        z = np.load(cache_path)
        return {"max_excursion": z["max_excursion"],
                "n_sim": n_sim, "applicable": True}
    rng = np.random.default_rng(seed)
    max_ex = np.zeros(n_sim)
    for i in range(n_sim):
        sim_draws = _simulate_history_as_draws(D, game, rng)
        r = cusum_drift_aggregate(sim_draws, game)
        max_ex[i] = r["max_excursion"]
    os.makedirs(CACHE_DIR, exist_ok=True)
    np.savez_compressed(cache_path, max_excursion=max_ex)
    return {"max_excursion": max_ex, "n_sim": n_sim, "applicable": True}

def mc_walk_forward_pvalue(observed: int, null: np.ndarray) -> Dict:
    return {
        "empirical_p": float(np.mean(null >= observed)),
        "null_mean": float(null.mean()),
        "null_std": float(null.std()),
        "null_p05": float(np.percentile(null, 5)),
        "null_p95": float(np.percentile(null, 95)),
        "n_sim": int(len(null)),
    }

