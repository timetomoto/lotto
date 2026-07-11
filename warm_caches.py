#!/usr/bin/env python3
"""Warm every disk cache under `data/mc_cache/` after a data refresh.

Called from `refresh_data.sh` on cron. Iterates each game and touches every
audit test's MC-null function plus the walk-forward null. Because the disk
caches are keyed on the CSV mtime signature, this run overwrites any stale
entries with fresh ones matching the newly-downloaded data. Streamlit's
in-memory cache is per-process and orthogonal — it repopulates on first user
render, but the *expensive* work (MC simulation) is already done here.

Safe to run standalone. Failures on any one game are logged and skipped;
the others still warm.
"""
from __future__ import annotations
import os
import sys
import time
import traceback

from games import GAMES
from loader import load_draws, filter_era, load_bonus_ball
from stats_tests import (
    chi_square_ball_frequency, chi_square_bonus_ball,
    chi_square_per_position_digit, chi_square_per_position_kn,
    ljung_box_per_ball, runs_test_draw_sums,
    gap_test_aggregate, pair_cooccurrence_aggregate,
    cusum_drift_aggregate, walk_forward_backtest,
)
from mc_null import (
    mc_walk_forward_null, mc_serial_dependence_null,
    mc_gap_test_null, mc_pair_cooccurrence_null, mc_cusum_drift_null,
)
from purchases import simulate_game as _purchase_simulate, STRATEGIES


def _warm_one_game(name: str) -> dict:
    g = GAMES[name]
    era = filter_era(load_draws(g), g)
    D = len(era)
    steps = []

    def do(label, fn):
        t = time.time()
        try:
            fn()
            steps.append((label, time.time() - t, None))
        except Exception as e:
            steps.append((label, time.time() - t, repr(e)))

    # Frequency chi-square — for kn games this triggers mc_chi_square_null_kn
    do("chi-square (+ MC null for kn)",
       lambda: chi_square_ball_frequency(era, g))

    # Walk-forward primary statistic + its MC null (quick preset)
    do("walk-forward statistic", lambda: walk_forward_backtest(era, g, burn_in=50))
    do("walk-forward MC null (n=200)",
       lambda: mc_walk_forward_null(g, D=D, burn_in=50, n_sim=200, seed=42))

    if g.game_type == "kn":
        do("serial deps observed",
           lambda: (ljung_box_per_ball(era, g, lags=10),
                    runs_test_draw_sums(era, g)))
        do("serial MC null",
           lambda: mc_serial_dependence_null(g, D=D, n_sim=100, seed=42,
                                             lags=10))
        do("gap-test observed",     lambda: gap_test_aggregate(era, g))
        do("gap-test MC null",
           lambda: mc_gap_test_null(g, D=D, n_sim=100, seed=42))
        do("pair observed",         lambda: pair_cooccurrence_aggregate(era, g))
        do("pair MC null",
           lambda: mc_pair_cooccurrence_null(g, D=D, n_sim=200, seed=42))
        do("drift observed",        lambda: cusum_drift_aggregate(era, g))
        do("drift MC null",
           lambda: mc_cusum_drift_null(g, D=D, n_sim=200, seed=42))
        do("per-position (kn)",     lambda: chi_square_per_position_kn(era, g))
        if g.bonus_n:
            do("bonus χ²",
               lambda: chi_square_bonus_ball(load_bonus_ball(g), g))
    else:
        do("per-position (digit)",
           lambda: chi_square_per_position_digit(era, g))
        do("serial deps observed (digit)",
           lambda: (ljung_box_per_ball(era, g, lags=10),
                    runs_test_draw_sums(era, g)))
        do("serial MC null (digit)",
           lambda: mc_serial_dependence_null(g, D=D, n_sim=100, seed=42,
                                             lags=10))

    # Purchase-log walk-forward simulations — one per (game, strategy).
    # These are the caches the Purchases tab reads; when they're missing,
    # first-visit Cloud page load blocks for tens of seconds while it
    # rebuilds them 3× per game.
    for strat in STRATEGIES:
        do(f"purchase log ({strat})",
           lambda s=strat: _purchase_simulate(name, strategy=s))

    return {"game": name, "steps": steps, "D": D}


def main() -> int:
    t0 = time.time()
    print(f"warm_caches @ {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    n_errors = 0
    for name in GAMES:
        gs = time.time()
        try:
            r = _warm_one_game(name)
            errs = [s for s in r["steps"] if s[2] is not None]
            n_errors += len(errs)
            status = "OK" if not errs else f"{len(errs)} step-error(s)"
            print(f"  {name:<16} D={r['D']:>6}  {time.time()-gs:6.1f}s  {status}")
            for lbl, dt, err in errs:
                print(f"    ! {lbl}: {err}")
        except Exception:
            n_errors += 1
            print(f"  {name:<16} FAILED after {time.time()-gs:.1f}s")
            traceback.print_exc()
    total = time.time() - t0
    print(f"warm_caches complete in {total:.1f}s "
          f"({n_errors} error(s))")
    return 0 if n_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
