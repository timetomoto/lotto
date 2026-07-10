"""Randomness test battery for k-of-N draw sequences.

NIST SP 800-22 is a bitstream battery and is deliberately not used here — see
findings.md §3. This module implements the classical Knuth/L'Ecuyer tests
appropriate for discrete uniform k-of-N samples.
"""
from typing import List, Tuple, Dict
from collections import Counter
import math
import numpy as np
from scipy.stats import chisquare, geom
from statsmodels.sandbox.stats.runs import runstest_1samp
from statsmodels.stats.diagnostic import acorr_ljungbox
from loader import Draw
from games import GameConfig

def chi_square_ball_frequency(draws: List[Draw], game: GameConfig,
                              mc_n_sim: int = 10_000, mc_seed: int = 42) -> Dict:
    """H0: uniform over the ball pool.

    For 'kn' games the textbook χ²(df=N−1) is MISCALIBRATED — the statistic
    has mean N−K under the true null (see mc_null.py). We report both:
    - `p_analytic`: the (conservative) chi-square-distribution p-value, kept
      for reference so users can see how much A1 mattered.
    - `p`: the Monte-Carlo empirical p-value, computed by simulating fair
      histories with the same D, K, N.
    For 'digit' games the per-position variant is genuinely uniform and the
    analytic p is exact; MC is skipped there.
    """
    c = Counter()
    for _, nums in draws:
        c.update(nums)
    N = game.n_main
    if game.game_type == "kn":
        observed = np.array([c.get(i, 0) for i in range(1, N + 1)])
        expected = np.full(N, len(draws) * game.k_main / N)
    else:
        observed = np.array([c.get(i, 0) for i in range(N)])
        expected = np.full(N, len(draws) * game.k_main / N)
    chi2_stat, p_analytic = chisquare(observed, expected)

    result = {
        "observed": observed, "expected": expected,
        "chi2": float(chi2_stat), "df": N - 1,
        "p_analytic": float(p_analytic),
        "p": float(p_analytic),  # default; overridden below for kn games
    }

    if game.game_type == "kn":
        from mc_null import mc_chi_square_null_kn
        null = mc_chi_square_null_kn(game, len(draws), n_sim=mc_n_sim,
                                     seed=mc_seed)
        p_empirical = float(np.mean(null >= chi2_stat))
        result.update({
            "p": p_empirical,
            "p_empirical": p_empirical,
            "null_mean": float(null.mean()),
            "null_expected_mean": float(N - game.k_main),
            "n_sim": int(len(null)),
        })
    return result

def chi_square_bonus_ball(values: List[int], game: GameConfig) -> Dict:
    """Chi-square for the bonus ball (K=1, so textbook χ²(df=N−1) is exact
    — bonus draws are IID uniform from a separate pool with no within-draw
    correlation).
    """
    N = game.bonus_n
    D = len(values)
    if D == 0 or N == 0:
        return {"chi2": float("nan"), "df": 0, "p": float("nan"),
                "observed": np.array([]), "expected": np.array([])}
    c = Counter(values)
    observed = np.array([c.get(i, 0) for i in range(1, N + 1)])
    expected = np.full(N, D / N)
    chi2_stat, p = chisquare(observed, expected)
    return {"observed": observed, "expected": expected,
            "chi2": float(chi2_stat), "df": N - 1, "p": float(p),
            "D": D, "N": N}

def chi_square_per_position_digit(draws: List[Draw], game: GameConfig) -> Dict:
    """For digit games only: chi-square per digit position; H0 uniform on 0..N-1."""
    assert game.game_type == "digit"
    per_pos = []
    for pos in range(game.k_main):
        c = Counter()
        for _, nums in draws:
            if pos < len(nums):
                c[nums[pos]] += 1
        obs = np.array([c.get(d, 0) for d in range(game.n_main)])
        n = obs.sum()
        exp = np.full(game.n_main, n / game.n_main)
        chi2, p = chisquare(obs, exp)
        per_pos.append({"position": pos, "observed": obs, "expected": exp,
                        "chi2": float(chi2), "df": game.n_main - 1, "p": float(p)})
    return {"per_position": per_pos}

def runs_test_above_below_median(draws: List[Draw], game: GameConfig) -> Dict:
    """Wald–Wolfowitz runs test on the sequence of draw *sums* vs. their median.
    Detects serial dependence in the aggregate draw statistic across time."""
    sums = np.array([sum(nums) for _, nums in draws], dtype=float)
    if len(sums) < 10:
        return {"stat": float("nan"), "p": float("nan"), "n": len(sums)}
    stat, p = runstest_1samp(sums, cutoff="median", correction=True)
    return {"stat": float(stat), "p": float(p), "n": len(sums)}

def gap_test_chi_square(draws: List[Draw], game: GameConfig, target_ball: int,
                       max_gap: int = 40) -> Dict:
    """For a single ball, gaps between consecutive appearances should follow
    a geometric distribution with success prob p = k/N under H0.
    Chi-square on binned gap frequencies vs. expected geometric.

    Adjacent bins are merged from the tail until every kept bin has expected
    count >= 5, per the standard chi-square small-cell rule. This also keeps
    sum(obs) == sum(exp) so scipy's chisquare accepts the input.
    """
    K, N = game.k_main, game.n_main
    p_hit = K / N
    positions = [i for i, (_, nums) in enumerate(draws) if target_ball in nums]
    if len(positions) < 5:
        return {"chi2": float("nan"), "p": float("nan"), "n_gaps": 0,
                "target_ball": target_ball}
    gaps = np.diff(positions)
    obs = np.zeros(max_gap + 1, dtype=float)
    for g in gaps:
        obs[min(g, max_gap + 1) - 1] += 1
    ks = np.arange(1, max_gap + 1)
    prob = (1 - p_hit) ** (ks - 1) * p_hit
    prob_tail = max(1.0 - prob.sum(), 0.0)
    exp = np.concatenate([prob, [prob_tail]]) * len(gaps)

    # Merge from the right until every kept bin has expected >= 5.
    merged_obs: List[float] = []
    merged_exp: List[float] = []
    running_obs = 0.0
    running_exp = 0.0
    for o, e in zip(reversed(obs), reversed(exp)):
        running_obs += o
        running_exp += e
        if running_exp >= 5:
            merged_obs.append(running_obs)
            merged_exp.append(running_exp)
            running_obs = 0.0
            running_exp = 0.0
    if running_exp > 0 and merged_exp:
        merged_obs[-1] += running_obs
        merged_exp[-1] += running_exp
    if len(merged_exp) < 2:
        return {"chi2": float("nan"), "p": float("nan"), "n_gaps": len(gaps),
                "target_ball": target_ball}
    obs_arr = np.array(list(reversed(merged_obs)))
    exp_arr = np.array(list(reversed(merged_exp)))
    # Guarantee equal sums (drops tiny float drift).
    exp_arr *= obs_arr.sum() / exp_arr.sum()
    chi2, p = chisquare(obs_arr, exp_arr)
    return {"chi2": float(chi2), "p": float(p), "n_gaps": len(gaps),
            "target_ball": target_ball, "n_bins": len(obs_arr)}

def ljung_box_on_ball_indicator(draws: List[Draw], game: GameConfig,
                                target_ball: int, lags: int = 10) -> Dict:
    """Ljung-Box on the indicator series 1{target_ball in draw_i}.
    Detects lag-k autocorrelation."""
    ind = np.array([1 if target_ball in nums else 0 for _, nums in draws],
                   dtype=float)
    if len(ind) < lags + 5:
        return {"stat": float("nan"), "p": float("nan"), "lags": lags}
    lb = acorr_ljungbox(ind, lags=[lags], return_df=True)
    return {"stat": float(lb["lb_stat"].iloc[0]), "p": float(lb["lb_pvalue"].iloc[0]),
            "lags": lags}

def paired_permutation_test(a: np.ndarray, b: np.ndarray,
                            n_perm: int = 10_000, seed: int = 0) -> Dict:
    """Two-sided paired permutation test on the mean difference a - b.

    Assumes each D_i = a_i − b_i is independently exchangeable — valid when
    both strategies are fixed a-priori and scored against independent
    draws (the Experiment-tab tracking case). NOT valid for
    walk-forward-vs-walk-forward comparisons, where consecutive D_i share
    almost their entire ticket history. Use `paired_block_permutation_test`
    for those.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    assert a.shape == b.shape
    obs = (a - b).mean()
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, len(a)))
    perm_means = (signs * (a - b)).mean(axis=1)
    p = float(np.mean(np.abs(perm_means) >= abs(obs)))
    return {"mean_diff": float(obs), "p": p, "n_perm": n_perm, "n": len(a)}

def paired_block_permutation_test(a: np.ndarray, b: np.ndarray,
                                  block_size: int = 20,
                                  n_perm: int = 10_000,
                                  seed: int = 0) -> Dict:
    """Paired permutation test that flips signs of contiguous *blocks* of
    D_i = a_i − b_i, rather than individual entries. Correct when the
    per-draw differences are serially correlated (e.g., both a and b are
    walk-forward strategies whose tickets evolve with shared history).

    Not currently wired into the app UI — the Experiment tab uses
    `paired_permutation_test` on locked (non-walk-forward) sequences where
    D_i are genuinely independent. This helper exists for future use if we
    add walk-forward-vs-walk-forward comparisons.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    assert a.shape == b.shape
    d = a - b
    n = len(d)
    obs = d.mean()
    n_blocks = (n + block_size - 1) // block_size
    rng = np.random.default_rng(seed)
    block_signs = rng.choice([-1.0, 1.0], size=(n_perm, n_blocks))
    # Expand each block sign to per-element signs of length n
    per_elem = np.repeat(block_signs, block_size, axis=1)[:, :n]
    perm_means = (per_elem * d).mean(axis=1)
    p = float(np.mean(np.abs(perm_means) >= abs(obs)))
    return {"mean_diff": float(obs), "p": p,
            "n_perm": n_perm, "n": n,
            "block_size": block_size, "n_blocks": n_blocks}

def chi_square_per_position_kn(draws: List[Draw], game: GameConfig) -> Dict:
    """Per-position chi-square for k-of-N games — tests whether each column
    of the CSV (assumed to be in draw order) is marginally uniform on 1..N.

    Under H₀ and preserved draw order, each position's marginal is uniform
    on 1..N with df = N − 1 (positions are correlated with each other but
    each is marginally uniform — the χ² is exact per position).
    """
    if game.game_type != "kn":
        return {"applicable": False, "per_position": []}
    D, K, N = len(draws), game.k_main, game.n_main
    results = []
    for pos in range(K):
        col = np.array([nums[pos] for _, nums in draws])
        counts = np.bincount(col, minlength=N + 1)[1:N + 1]
        expected = np.full(N, D / N)
        chi2_stat, p = chisquare(counts, expected)
        results.append({
            "position": pos, "chi2": float(chi2_stat),
            "df": N - 1, "p": float(p),
        })
    return {"applicable": True, "per_position": results}

def holm_correction(raw_ps: List[float]) -> List[float]:
    """Holm–Bonferroni step-down adjustment. Given m raw p-values, returns
    adjusted p-values that control family-wise error rate at any α ≥
    max(adjusted). Order of the input list is preserved in the output.
    """
    m = len(raw_ps)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: raw_ps[i])
    adj_sorted = [0.0] * m
    running_max = 0.0
    for rank, idx in enumerate(order):
        # rank 0 gets multiplier m, rank 1 gets m-1, etc.
        adj = raw_ps[idx] * (m - rank)
        adj = min(1.0, adj)
        running_max = max(running_max, adj)
        adj_sorted[rank] = running_max
    out = [0.0] * m
    for rank, idx in enumerate(order):
        out[idx] = adj_sorted[rank]
    return out

def cusum_drift_aggregate(draws: List[Draw], game: GameConfig) -> Dict:
    """CUSUM-style drift detector (k-of-N games).

    For each ball, compute the cumulative deviation from its expected
    per-draw rate p = K/N. Under H₀ this walks as a mean-zero random
    process; large excursions indicate the ball's drawing rate drifted
    over time even if its lifetime average looks normal.

    Reports the max absolute excursion across all balls and time. The
    aggregate is MC-calibrated (see mc_null.mc_cusum_drift_null).
    """
    if game.game_type != "kn":
        return {"applicable": False}
    K, N = game.k_main, game.n_main
    D = len(draws)
    p = K / N
    X = np.zeros((D, N), dtype=np.float64)
    for t, (_, nums) in enumerate(draws):
        for b in nums:
            X[t, b - 1] = 1
    dev = X - p
    cum = dev.cumsum(axis=0)  # (D, N)
    per_ball_max = np.abs(cum).max(axis=0)  # (N,)
    return {
        "applicable": True,
        "max_excursion": float(per_ball_max.max()),
        "worst_ball": int(np.argmax(per_ball_max) + 1),
        "n_balls": N,
        "cumsum": cum,
    }

def rolling_frequency(draws: List[Draw], game: GameConfig, ball: int,
                      window: int) -> np.ndarray:
    """Rolling-window count of `ball` appearances over `window` draws.
    Returns array of length D - window + 1 (or empty if too few draws)."""
    if game.game_type != "kn":
        return np.array([])
    D = len(draws)
    if D < window:
        return np.array([])
    ind = np.array([1 if ball in nums else 0 for _, nums in draws],
                   dtype=np.float64)
    cum = np.concatenate([[0.0], ind.cumsum()])
    return cum[window:] - cum[:-window]

def pair_cooccurrence_aggregate(draws: List[Draw], game: GameConfig) -> Dict:
    """Pairwise co-occurrence audit for k-of-N games.

    Under H₀, each ball pair (b, b') has probability
        p_pair = K(K-1) / [N(N-1)]
    of both appearing in any given draw. Across D draws each pair count is
    approximately Binomial(D, p_pair) with mean D·p_pair and variance
    D·p_pair·(1 − p_pair).

    Returns:
      - obs_matrix: NxN symmetric matrix of pair counts (diagonal is per-ball
                    count, upper triangle is the pairwise data).
      - max_z:      largest |z-score| across all pairs.
      - top_pairs:  the 5 pairs with the largest deviations from expected.
      - chi2_like:  Σ (O − E)² / E summed over pairs; a single scalar
                    aggregate for MC calibration.
    """
    if game.game_type != "kn":
        return {"applicable": False}
    K, N = game.k_main, game.n_main
    D = len(draws)
    # Build indicator matrix (D, N) then X^T @ X gives co-occurrence.
    # Build indicator matrix as int32 — int8 matmul overflows for large D.
    X = np.zeros((D, N), dtype=np.int32)
    for t, (_, nums) in enumerate(draws):
        for b in nums:
            X[t, b - 1] = 1
    co = (X.T @ X).astype(np.float64)
    p_pair = K * (K - 1) / (N * (N - 1))
    E = D * p_pair
    var = D * p_pair * (1 - p_pair)
    sd = np.sqrt(var) if var > 0 else 1.0
    # Extract upper triangle (i < j) as pair vector
    iu, ju = np.triu_indices(N, k=1)
    obs_pairs = co[iu, ju]
    z_pairs = (obs_pairs - E) / sd if sd > 0 else np.zeros_like(obs_pairs)
    max_z_idx = int(np.argmax(np.abs(z_pairs)))
    order = np.argsort(-np.abs(z_pairs))
    top_pairs = [
        {"b1": int(iu[k] + 1), "b2": int(ju[k] + 1),
         "obs": int(obs_pairs[k]), "exp": float(E),
         "z": float(z_pairs[k])}
        for k in order[:5]
    ]
    chi2_like = float(np.sum((obs_pairs - E) ** 2 / E)) if E > 0 else float("nan")
    return {
        "applicable": True,
        "expected_per_pair": float(E),
        "max_z": float(np.max(np.abs(z_pairs))),
        "top_pairs": top_pairs,
        "chi2_like": chi2_like,
        "n_pairs": int(len(obs_pairs)),
    }

def gap_test_aggregate(draws: List[Draw], game: GameConfig) -> Dict:
    """Aggregate gap-test statistics across all balls (kn games only).

    For each ball, the gap between consecutive appearances should be
    Geometric(K/N) under H₀. `gap_test_chi_square` computes the χ² fit
    per ball; here we roll them up into two summaries:
      - max_chi2: worst-fitting ball's statistic
      - prop_below_05: fraction of balls with gap-test p < 0.05
    """
    if game.game_type != "kn":
        return {"applicable": False}
    stats_arr = []
    ps_arr = []
    for b in range(1, game.n_main + 1):
        r = gap_test_chi_square(draws, game, target_ball=b)
        if not np.isnan(r["chi2"]):
            stats_arr.append(r["chi2"])
            ps_arr.append(r["p"])
    stats = np.array(stats_arr)
    ps = np.array(ps_arr)
    return {
        "applicable": True,
        "stats": stats, "ps": ps,
        "max_stat": float(stats.max()) if len(stats) else float("nan"),
        "min_p": float(ps.min()) if len(ps) else float("nan"),
        "prop_below_05": float(np.mean(ps < 0.05)) if len(ps) else float("nan"),
        "n_balls": int(len(stats)),
    }

def ljung_box_per_ball(draws: List[Draw], game: GameConfig,
                       lags: int = 10) -> Dict:
    """For each ball (kn) or (position, digit) pair (digit games), compute
    the Ljung-Box statistic on its indicator time series. This is the
    primary serial-independence test: it catches per-ball clumping.

    Returns dict with:
        - stats:    array of LB statistics, one per ball / (pos, digit)
        - ps:       array of LB p-values (from χ²(lags) — approximate; the
                    aggregate null distribution is MC-calibrated instead of
                    trusting the per-ball approximation).
        - prop_below_05: fraction of series with p < 0.05
        - max_stat: maximum LB statistic across all series (single-signal
                    aggregation — catches any one ball with strong lag-k
                    autocorrelation).
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox
    K, N = game.k_main, game.n_main
    stats_arr: List[float] = []
    ps_arr: List[float] = []

    if game.game_type == "kn":
        for b in range(1, N + 1):
            ind = np.fromiter(
                (1 if b in nums else 0 for _, nums in draws),
                dtype=np.int8, count=len(draws),
            ).astype(float)
            if len(ind) < lags + 5:
                continue
            try:
                lb = acorr_ljungbox(ind, lags=[lags], return_df=True)
                stats_arr.append(float(lb["lb_stat"].iloc[0]))
                ps_arr.append(float(lb["lb_pvalue"].iloc[0]))
            except Exception:
                continue
    else:
        for pos in range(K):
            for d in range(N):
                ind = np.fromiter(
                    (1 if (pos < len(nums) and nums[pos] == d) else 0
                     for _, nums in draws),
                    dtype=np.int8, count=len(draws),
                ).astype(float)
                if len(ind) < lags + 5:
                    continue
                try:
                    lb = acorr_ljungbox(ind, lags=[lags], return_df=True)
                    stats_arr.append(float(lb["lb_stat"].iloc[0]))
                    ps_arr.append(float(lb["lb_pvalue"].iloc[0]))
                except Exception:
                    continue

    stats = np.array(stats_arr)
    ps = np.array(ps_arr)
    return {
        "stats": stats, "ps": ps, "lags": lags,
        "max_stat": float(stats.max()) if len(stats) else float("nan"),
        "min_p": float(ps.min()) if len(ps) else float("nan"),
        "prop_below_05": float(np.mean(ps < 0.05)) if len(ps) else float("nan"),
        "n_series": int(len(stats)),
    }

def runs_test_draw_sums(draws: List[Draw], game: GameConfig) -> Dict:
    """Wald-Wolfowitz runs test on the sequence of draw sums vs. their median.
    A coarser secondary summary of serial dependence — collapsing K balls to
    one sum discards most of the structure that Ljung-Box catches, but it's
    a familiar single-p-value signal."""
    from statsmodels.sandbox.stats.runs import runstest_1samp
    sums = np.array([sum(nums) for _, nums in draws], dtype=float)
    if len(sums) < 10:
        return {"stat": float("nan"), "p": float("nan"), "n": len(sums)}
    stat, p = runstest_1samp(sums, cutoff="median", correction=True)
    return {"stat": float(stat), "p": float(p), "n": len(sums)}

def walk_forward_backtest(draws, game: GameConfig, burn_in: int = 50) -> Dict:
    """Honest out-of-sample backtest of the S1 (top-K most-frequent) strategy.

    Procedure: walk through history chronologically. At each draw t >= burn_in,
    derive S1 from *only* the draws that happened before t (i.e., draws[0:t]),
    then score that S1 against the newly seen draw[t]. Aggregate the match
    counts.

    This restores ticket-draw independence at each step — S1 was chosen
    before the draw it was scored against. Under H0 the observed match
    distribution should now land squarely on the theoretical Hypergeometric
    (or Binomial for digit games); large deviations would be real signal.
    """
    from collections import Counter
    from scipy.stats import hypergeom, binom
    from strategies import s1_from_counter, s1_from_position_counters
    K, N = game.k_main, game.n_main
    per_draw = []

    if game.game_type == "kn":
        c: Counter = Counter()
        for t, (_, nums) in enumerate(draws):
            if t >= burn_in:
                s1_set = set(s1_from_counter(c, K, N))
                per_draw.append(len(s1_set & set(nums)))
            c.update(nums)
    else:
        counters = [Counter() for _ in range(K)]
        for t, (_, nums) in enumerate(draws):
            if t >= burn_in:
                s1 = s1_from_position_counters(counters, K, N)
                per_draw.append(sum(1 for i, n in enumerate(nums)
                                    if i < len(s1) and n == s1[i]))
            for i, n in enumerate(nums):
                if i < K:
                    counters[i][n] += 1

    obs_counts = [0] * (K + 1)
    for m in per_draw:
        if 0 <= m <= K:
            obs_counts[m] += 1
    n_scored = len(per_draw)
    if game.game_type == "kn":
        exp_prop = [float(hypergeom.pmf(m, N, K, K)) for m in range(K + 1)]
    else:
        exp_prop = [float(binom.pmf(m, K, 1.0 / N)) for m in range(K + 1)]
    exp_counts = [p * n_scored for p in exp_prop]

    return {
        "per_draw": per_draw,
        "obs_counts": obs_counts,
        "exp_counts": exp_counts,
        "exp_prop": exp_prop,
        "n_scored": n_scored,
        "burn_in": burn_in,
        "K": K, "N": N,
    }

def historical_match_distribution(draws, sequence, game: GameConfig) -> Dict:
    """For a fixed sequence (e.g., S1), count how often it matched 0..K balls
    across each historical draw. Compares against the theoretical
    Hypergeometric(N,K,K) for kn games or Binomial(K, 1/N) for digit games.

    Note: this is a data-snooped backtest when the sequence was derived from
    the same draws. Under H₀ the observed distribution should still match the
    theoretical — that's the point of the comparison.
    """
    from scipy.stats import hypergeom, binom
    seq_set = set(sequence)
    K, N = game.k_main, game.n_main
    per_draw = []
    for _, nums in draws:
        if game.game_type == "kn":
            per_draw.append(len(seq_set & set(nums)))
        else:
            per_draw.append(sum(1 for i, n in enumerate(nums)
                                if i < len(sequence) and n == sequence[i]))
    total = len(per_draw)
    obs_counts = [0] * (K + 1)
    for m in per_draw:
        if 0 <= m <= K:
            obs_counts[m] += 1
    obs_prop = [c / total for c in obs_counts]
    if game.game_type == "kn":
        exp_prop = [float(hypergeom.pmf(m, N, K, K)) for m in range(K + 1)]
    else:
        exp_prop = [float(binom.pmf(m, K, 1.0 / N)) for m in range(K + 1)]
    exp_counts = [p * total for p in exp_prop]
    return {
        "total_draws": total, "per_draw": per_draw,
        "obs_counts": obs_counts, "exp_counts": exp_counts,
        "obs_prop": obs_prop, "exp_prop": exp_prop,
        "K": K, "N": N,
    }

def null_band_for_matches(game: GameConfig, n_draws: int, ci: float = 0.95) -> Tuple[float, float, float, float]:
    """(mean_per_draw, sd_per_draw, band_low_total, band_high_total) under H0.

    - k-of-N: matches ~ Hypergeometric(N, K, K), μ=K²/N, σ²=K²(N-K)²/(N²(N-1))
    - digit:  matches ~ Binomial(K, 1/N),        μ=K/N,   σ²=K(N-1)/N²
    """
    K, N = game.k_main, game.n_main
    if game.game_type == "kn":
        mean = (K * K) / N
        var = K * K * (N - K) * (N - K) / (N * N * (N - 1))
    else:
        mean = K / N
        var = K * (N - 1) / (N * N)
    sd = math.sqrt(var)
    z = 1.96 if abs(ci - 0.95) < 1e-6 else 2.576
    tot_mean = n_draws * mean
    tot_sd = math.sqrt(n_draws) * sd
    return mean, sd, tot_mean - z * tot_sd, tot_mean + z * tot_sd
