"""Game configurations for the current Texas Lottery formats (2026-07-10).

Two game types:
- 'kn'    — k-of-N without replacement (standard draw games). Sample space is
            combinations of `k_main` distinct balls from 1..`n_main`.
- 'digit' — `k_main` positions of independent digits, each in 0..(`n_main`-1).
            Under H0 each position is uniform on the alphabet with replacement.
            Sample space is `n_main` ** `k_main`.

For digit games the tracking-experiment expected match rate is K * (1/N) per
draw — with 3 digits × 0.1 that's 0.3 matches/draw, and the exact-match rate
is 1/N**K (e.g., 1/1000 for Pick 3). Over 50 draws the expected exact matches
are <0.1, so the tracking experiment is essentially not detectable for digit
games — audit-only.
"""
from datetime import date
from dataclasses import dataclass, field
from typing import List, Literal

@dataclass(frozen=True)
class GameConfig:
    name: str
    csv_paths: tuple                 # one or more CSVs (multi-file games merge)
    game_type: Literal["kn", "digit"]
    k_main: int                      # balls-per-draw (kn) or digit positions (digit)
    n_main: int                      # ball range 1..N (kn) or alphabet size (digit, 10)
    main_slice_len: int              # width of the main-number slice in the CSV row
    era_start: date
    schedule: str
    draws_per_week: int
    ticket_cost: str = ""            # display string, e.g. "$1" or "$0.50+"
    draw_weekdays: tuple = ()        # 0=Mon..6=Sun, weekdays on which the game draws
    draws_per_day: int = 1           # 1 for standard games, 4 for morning/day/evening/night
    draw_times: tuple = ()           # "HH:MM" in Central Time, per draw slot per day
    ticket_cost_low: float = 0.0     # numeric single-play cost (for total-cost calc)
    kn_experiment_ok: bool = True    # whether tracking-experiment is meaningful
    bonus_n: int = 0                 # 0 = no bonus ball; else the bonus-pool size
    bonus_col_offset: int = 0        # column offset from row[4+main_slice_len]
    bonus_label: str = ""            # display name of the bonus ball

GAMES = {
    # ---- k-of-N games (tracking experiment applies) ----
    "Lotto Texas": GameConfig(
        name="Lotto Texas",
        csv_paths=("data/lotto_texas.csv",),
        game_type="kn",
        k_main=6, n_main=54, main_slice_len=6,
        era_start=date(2006, 1, 1),
        schedule="Mon / Wed / Sat", draws_per_week=3,
        ticket_cost="$1 per play", ticket_cost_low=1.0,
        draw_weekdays=(0, 2, 5), draws_per_day=1,
        draw_times=("22:12",),
    ),
    "Mega Millions": GameConfig(
        name="Mega Millions",
        csv_paths=("data/mega_millions.csv",),
        game_type="kn",
        k_main=5, n_main=70, main_slice_len=5,
        era_start=date(2017, 10, 28),
        schedule="Tue / Fri", draws_per_week=2,
        ticket_cost="$5 per play", ticket_cost_low=5.0,
        draw_weekdays=(1, 4), draws_per_day=1,
        draw_times=("22:12",),
        bonus_n=25, bonus_col_offset=0, bonus_label="Mega Ball",
    ),
    "Powerball": GameConfig(
        name="Powerball",
        csv_paths=("data/powerball.csv",),
        game_type="kn",
        k_main=5, n_main=69, main_slice_len=5,
        era_start=date(2015, 10, 4),
        schedule="Mon / Wed / Sat", draws_per_week=3,
        ticket_cost="$2 per play", ticket_cost_low=2.0,
        draw_weekdays=(0, 2, 5), draws_per_day=1,
        draw_times=("22:12",),
        bonus_n=26, bonus_col_offset=0, bonus_label="Powerball",
    ),
    "Cash Five": GameConfig(
        name="Cash Five",
        csv_paths=("data/cash_five.csv",),
        game_type="kn",
        k_main=5, n_main=35, main_slice_len=5,
        era_start=date(2019, 1, 1),
        schedule="Mon–Sat (daily)", draws_per_week=6,
        ticket_cost="$1 per play", ticket_cost_low=1.0,
        draw_weekdays=(0, 1, 2, 3, 4, 5), draws_per_day=1,
        draw_times=("22:12",),
    ),
    "Texas Two Step": GameConfig(
        name="Texas Two Step",
        csv_paths=("data/texas_two_step.csv",),
        game_type="kn",
        k_main=4, n_main=35, main_slice_len=4,
        era_start=date(2001, 5, 18),
        schedule="Mon / Thu", draws_per_week=2,
        ticket_cost="$1 per play", ticket_cost_low=1.0,
        draw_weekdays=(0, 3), draws_per_day=1,
        draw_times=("22:12",),
        bonus_n=35, bonus_col_offset=0, bonus_label="Bonus Ball",
    ),
    "All or Nothing": GameConfig(
        name="All or Nothing",
        csv_paths=(
            "data/all_or_nothing_morning.csv",
            "data/all_or_nothing_day.csv",
            "data/all_or_nothing_evening.csv",
            "data/all_or_nothing_night.csv",
        ),
        game_type="kn",
        k_main=12, n_main=24, main_slice_len=12,
        era_start=date(2012, 9, 10),
        schedule="Mon–Sat × 4 daily draws", draws_per_week=24,
        ticket_cost="$2 per play", ticket_cost_low=2.0,
        draw_weekdays=(0, 1, 2, 3, 4, 5), draws_per_day=4,
        draw_times=("10:00", "12:27", "18:00", "22:12"),
    ),
    # ---- Digit games (audit only; tracking not applicable) ----
    "Pick 3": GameConfig(
        name="Pick 3",
        csv_paths=(
            "data/pick_3_morning.csv",
            "data/pick_3_day.csv",
            "data/pick_3_evening.csv",
            "data/pick_3_night.csv",
        ),
        game_type="digit",
        k_main=3, n_main=10, main_slice_len=3,
        era_start=date(2013, 9, 9),
        schedule="Mon–Sat × 4 draws", draws_per_week=24,
        ticket_cost="$0.50 – $5 per play", ticket_cost_low=0.5,
        draw_weekdays=(0, 1, 2, 3, 4, 5), draws_per_day=4,
        draw_times=("10:00", "12:27", "18:00", "22:12"),
        kn_experiment_ok=False,
    ),
    "Daily 4": GameConfig(
        name="Daily 4",
        csv_paths=(
            "data/daily_4_morning.csv",
            "data/daily_4_day.csv",
            "data/daily_4_evening.csv",
            "data/daily_4_night.csv",
        ),
        game_type="digit",
        k_main=4, n_main=10, main_slice_len=4,
        era_start=date(2013, 9, 9),
        schedule="Mon–Sat × 4 draws", draws_per_week=24,
        ticket_cost="$0.50 – $5 per play", ticket_cost_low=0.5,
        draw_weekdays=(0, 1, 2, 3, 4, 5), draws_per_day=4,
        draw_times=("10:00", "12:27", "18:00", "22:12"),
        kn_experiment_ok=False,
    ),
}
