"""Draw-schedule projection: upcoming draws per game.

The upcoming schedule is computed from `draw_weekdays` and `draws_per_day` in
each `GameConfig`. Multi-daily games (All or Nothing, Pick 3, Daily 4) are
listed as a single row per day with a note on the four draw times.

Draw times reflect the Texas Lottery's published cadence but are not stored
per-draw in the CSVs, so this module treats each draw day as one row.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import List, Dict
from games import GAMES, GameConfig

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday"]

def upcoming_draws(days_ahead: int = 14, start: date | None = None,
                   include_inactive: bool = False) -> List[Dict]:
    """Return list of scheduled draws for the next `days_ahead` days.

    Each entry: {date, weekday, game, active, draws_per_day, cost_low, ...}.

    If `include_inactive` is True, every game appears in every day's list
    with `active=False` on days it doesn't draw (draws_per_day and cost_low
    are still the game's underlying values for reference). Otherwise only
    active game/day combinations are returned.
    """
    if start is None:
        start = date.today()
    rows = []
    for i in range(days_ahead):
        dt = start + timedelta(days=i)
        for name, g in GAMES.items():
            active = dt.weekday() in g.draw_weekdays
            if not active and not include_inactive:
                continue
            rows.append({
                "date": dt,
                "weekday": DAYS[dt.weekday()],
                "game": name,
                "active": active,
                "draws_per_day": g.draws_per_day,
                "cost_low": g.ticket_cost_low,
                "cost_display": g.ticket_cost,
            })
    return rows

def per_day_cost(games_playing: List[str], date_: date) -> float:
    """Minimum daily spend if playing one ticket for every scheduled draw
    (multi-daily games count each of their four draws)."""
    total = 0.0
    for name in games_playing:
        g = GAMES[name]
        if date_.weekday() in g.draw_weekdays:
            total += g.ticket_cost_low * g.draws_per_day
    return total
