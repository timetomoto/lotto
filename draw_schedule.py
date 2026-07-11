"""Draw-schedule projection: upcoming draws per game.

The upcoming schedule is computed from `draw_weekdays` and `draws_per_day` in
each `GameConfig`. Multi-daily games (All or Nothing, Pick 3, Daily 4) are
listed as a single row per day with a note on the four draw times.

`next_draw_datetime` returns the next scheduled draw as a timezone-aware
datetime in America/Chicago, honoring the game's `draw_times` and DST.
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from typing import List, Dict, Optional
from zoneinfo import ZoneInfo
from games import GAMES, GameConfig

CT = ZoneInfo("America/Chicago")

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

def next_draw_datetime(game: GameConfig,
                       now_ct: Optional[datetime] = None
                       ) -> Optional[datetime]:
    """Return the next scheduled draw as a tz-aware datetime in
    America/Chicago, honoring the game's draw_weekdays and draw_times.
    Returns None if the game has no configured draw times (shouldn't
    happen for current games)."""
    if not game.draw_times or not game.draw_weekdays:
        return None
    if now_ct is None:
        now_ct = datetime.now(CT)
    # Look up to 8 days ahead — enough to skip Sunday even in edge cases.
    for days_ahead in range(0, 9):
        day = (now_ct + timedelta(days=days_ahead)).date()
        if day.weekday() not in game.draw_weekdays:
            continue
        for t_str in game.draw_times:
            hh, mm = (int(x) for x in t_str.split(":"))
            dt = datetime.combine(day, time(hh, mm), tzinfo=CT)
            if dt > now_ct:
                return dt
    return None

