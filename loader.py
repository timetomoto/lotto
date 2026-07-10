"""CSV loading for k-of-N and digit games; merges multi-file games; era filter."""
import csv
from datetime import date
from typing import List, Tuple
from games import GameConfig

Draw = Tuple[date, Tuple[int, ...]]  # (draw_date, K-tuple of main numbers/digits)

def _load_one(path: str, game: GameConfig) -> List[Draw]:
    out: List[Draw] = []
    with open(path) as f:
        for row in csv.reader(f):
            if len(row) < 4 + game.main_slice_len:
                continue
            try:
                dt = date(int(row[3]), int(row[1]), int(row[2]))
            except (ValueError, IndexError):
                continue
            raw = row[4:4 + game.main_slice_len]
            try:
                main = tuple(int(x) for x in raw if x.strip() != "")
            except ValueError:
                continue
            if len(main) != game.main_slice_len:
                continue
            if game.game_type == "kn":
                if any(b < 1 or b > game.n_main for b in main):
                    continue
                if len(set(main)) != len(main):  # k-of-N draws are without-replacement
                    continue
            elif game.game_type == "digit":
                if any(d < 0 or d >= game.n_main for d in main):
                    continue
            out.append((dt, main))
    return out

def load_draws(game: GameConfig) -> List[Draw]:
    all_draws: List[Draw] = []
    for p in game.csv_paths:
        all_draws.extend(_load_one(p, game))
    return sorted(all_draws, key=lambda r: r[0])

def filter_era(draws: List[Draw], game: GameConfig) -> List[Draw]:
    return [d for d in draws if d[0] >= game.era_start]

def load_draws_full(game: GameConfig) -> List[dict]:
    """Return list of dicts: {date, slot, main, bonus} for the era.

    - `slot` is the capitalized slot name (Morning/Day/Evening/Night) for
      multi-file games, or None for single-file games.
    - `bonus` is the bonus-ball integer for games with bonus_n>0, else None.
    """
    out: List[dict] = []
    multi = len(game.csv_paths) > 1
    for path in game.csv_paths:
        slot = None
        if multi:
            base = path.rsplit("/", 1)[-1].replace(".csv", "").lower()
            for s in ("morning", "day", "evening", "night"):
                if base.endswith("_" + s):
                    slot = s.capitalize()
                    break
        with open(path) as f:
            for row in csv.reader(f):
                if len(row) < 4 + game.main_slice_len:
                    continue
                try:
                    dt = date(int(row[3]), int(row[1]), int(row[2]))
                except (ValueError, IndexError):
                    continue
                if dt < game.era_start:
                    continue
                raw = row[4:4 + game.main_slice_len]
                try:
                    main = tuple(int(x) for x in raw if x.strip() != "")
                except ValueError:
                    continue
                if len(main) != game.main_slice_len:
                    continue
                if game.game_type == "kn":
                    if any(b < 1 or b > game.n_main for b in main):
                        continue
                    if len(set(main)) != len(main):
                        continue
                else:
                    if any(d < 0 or d >= game.n_main for d in main):
                        continue
                bonus = None
                if game.bonus_n:
                    bc = 4 + game.main_slice_len + game.bonus_col_offset
                    if len(row) > bc and row[bc].strip():
                        try:
                            bv = int(row[bc])
                            if 1 <= bv <= game.bonus_n:
                                bonus = bv
                        except ValueError:
                            pass
                out.append({"date": dt, "slot": slot,
                            "main": main, "bonus": bonus})
    return sorted(out, key=lambda r: (r["date"], r["slot"] or ""))

def load_bonus_ball(game: GameConfig) -> List[int]:
    """Return the bonus-ball values for a game, filtered to era. Empty list
    if the game has no bonus ball or the value is out of range."""
    if not game.bonus_n:
        return []
    col = 4 + game.main_slice_len + game.bonus_col_offset
    out = []
    for path in game.csv_paths:
        with open(path) as f:
            for row in csv.reader(f):
                try:
                    dt = date(int(row[3]), int(row[1]), int(row[2]))
                except (ValueError, IndexError):
                    continue
                if dt < game.era_start:
                    continue
                if len(row) <= col or not row[col].strip():
                    continue
                try:
                    val = int(row[col])
                except ValueError:
                    continue
                if 1 <= val <= game.bonus_n:
                    out.append(val)
    return out
