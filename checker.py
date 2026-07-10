"""Ticket-vs-draw prize checker for every Texas Lottery game.

Given a user's picks and a specific historical draw, return a structured
result: {win, matches, tier, prize, note}. `prize` is a numeric best-effort
based on published fixed-prize tiers; where the prize varies by draw
(jackpots, some pari-mutuel tiers), `prize` is `None` and `note` explains.

Supported play modes:
  - Simple k-of-N (Lotto Texas, Cash Five)
  - k-of-N + bonus ball (Powerball, Mega Millions, Texas Two Step)
  - Symmetric all-or-nothing (All or Nothing — win for matching all 12 OR none)
  - Digit games (Pick 3, Daily 4) with play types:
      Straight, Box, Straight/Box, Front Pair, Back Pair

Not modelled (yet): Extra!, Power Play, Megaplier multipliers; Combo;
Sum It Up!; Fireball. These change prize amounts; the "note" field in
every return mentions the omission.
"""
from __future__ import annotations
from collections import Counter
from typing import Optional, Tuple, Dict, Iterable
from games import GAMES, GameConfig


# --------------------------------------------------------------------
# Simple k-of-N (Lotto Texas, Cash Five)
# --------------------------------------------------------------------

_SIMPLE_KN_PRIZE = {
    "Lotto Texas": {
        6: ("Jackpot — match 6 of 6", None,
            "Jackpot varies by drawing (starts at $5M, rolls if no winner)."),
        5: ("Match 5 of 6", 1239,
            "Pari-mutuel — actual ~$1,000–$1,500 depending on winners."),
        4: ("Match 4 of 6", 38,
            "Pari-mutuel — actual ~$30–$50."),
        3: ("Match 3 of 6", 3, "$3 fixed."),
    },
    "Cash Five": {
        5: ("Match 5 of 5", 25_000, "$25,000 top prize."),
        4: ("Match 4 of 5", 350, "$350 fixed."),
        3: ("Match 3 of 5", 15, "$15 fixed."),
        2: ("Match 2 of 5", None, "Free Cash Five ticket."),
    },
}

def check_simple_kn(user_pick: Iterable[int], draw: Iterable[int],
                    game_name: str) -> Dict:
    """For Lotto Texas / Cash Five: match count → prize tier."""
    user_set, draw_set = set(user_pick), set(draw)
    matches = len(user_set & draw_set)
    table = _SIMPLE_KN_PRIZE.get(game_name, {})
    if matches in table:
        label, prize, note = table[matches]
        return {"win": True, "matches": matches, "tier": label,
                "prize": prize, "note": note}
    return {"win": False, "matches": matches, "tier": "No prize",
            "prize": 0, "note": ""}


# --------------------------------------------------------------------
# k-of-N + bonus (Powerball, Mega Millions, Texas Two Step)
# --------------------------------------------------------------------

# Key: (main_matches, bonus_hit) → (label, prize, note)
_BONUS_KN_PRIZE = {
    "Powerball": {
        (5, True):  ("5 + Powerball — Jackpot", None, "Jackpot varies."),
        (5, False): ("Match 5",                 1_000_000, "$1,000,000 fixed."),
        (4, True):  ("Match 4 + Powerball",     50_000, "$50,000 fixed."),
        (4, False): ("Match 4",                 100, "$100 fixed."),
        (3, True):  ("Match 3 + Powerball",     100, "$100 fixed."),
        (3, False): ("Match 3",                 7, "$7 fixed."),
        (2, True):  ("Match 2 + Powerball",     7, "$7 fixed."),
        (1, True):  ("Match 1 + Powerball",     4, "$4 fixed."),
        (0, True):  ("Powerball only",          4, "$4 fixed."),
    },
    "Mega Millions": {
        (5, True):  ("5 + Mega Ball — Jackpot", None, "Jackpot varies."),
        (5, False): ("Match 5",                 1_000_000, "$1,000,000 fixed."),
        (4, True):  ("Match 4 + Mega Ball",     10_000, "$10,000 fixed."),
        (4, False): ("Match 4",                 500, "$500 fixed."),
        (3, True):  ("Match 3 + Mega Ball",     200, "$200 fixed."),
        (3, False): ("Match 3",                 10, "$10 fixed."),
        (2, True):  ("Match 2 + Mega Ball",     10, "$10 fixed."),
        (1, True):  ("Match 1 + Mega Ball",     7, "$7 fixed."),
        (0, True):  ("Mega Ball only",          5, "$5 fixed."),
    },
    "Texas Two Step": {
        (4, True):  ("4 + Bonus — Jackpot",     None, "Jackpot varies."),
        (4, False): ("Match 4",                 1_638, "Pari-mutuel — actual varies."),
        (3, True):  ("Match 3 + Bonus",         50, "$50 fixed."),
        (3, False): ("Match 3",                 19, "Pari-mutuel — actual ~$20."),
        (2, True):  ("Match 2 + Bonus",         21, "Pari-mutuel — actual ~$21."),
        (1, True):  ("Match 1 + Bonus",         7, "$7 fixed."),
        (0, True):  ("Bonus only",              5, "$5 fixed."),
    },
}

def check_kn_bonus(user_main: Iterable[int], user_bonus: int,
                   draw_main: Iterable[int], draw_bonus: Optional[int],
                   game_name: str) -> Dict:
    """For Powerball / Mega Millions / Texas Two Step."""
    user_set, draw_set = set(user_main), set(draw_main)
    matches = len(user_set & draw_set)
    bonus_hit = (draw_bonus is not None) and (user_bonus == draw_bonus)
    table = _BONUS_KN_PRIZE.get(game_name, {})
    key = (matches, bonus_hit)
    if key in table:
        label, prize, note = table[key]
        return {"win": True, "matches": matches, "bonus_match": bonus_hit,
                "tier": label, "prize": prize, "note": note}
    return {"win": False, "matches": matches, "bonus_match": bonus_hit,
            "tier": "No prize", "prize": 0, "note": ""}


# --------------------------------------------------------------------
# All or Nothing — win top prize for matching all 12 or matching 0
# --------------------------------------------------------------------

_AON_TIERS = {
    12: (250_000, "Top prize (all 12)"),
    11: (500,      "2nd tier"),
    10: (50,       "3rd tier"),
    9:  (10,       "4th tier"),
    8:  (2,        "5th tier"),
    #    matches 5, 6, 7 do NOT win
    4:  (2,        "5th tier (matching 4)"),
    3:  (10,       "4th tier (matching 3)"),
    2:  (50,       "3rd tier (matching 2)"),
    1:  (500,      "2nd tier (matching 1)"),
    0:  (250_000, "Top prize (matching 0)"),
}

def check_all_or_nothing(user_pick: Iterable[int],
                        draw: Iterable[int]) -> Dict:
    user_set, draw_set = set(user_pick), set(draw)
    matches = len(user_set & draw_set)
    if matches in _AON_TIERS:
        prize, tier = _AON_TIERS[matches]
        return {"win": True, "matches": matches,
                "tier": f"{tier} — {matches} matched",
                "prize": prize,
                "note": "Wins for matching either all 12 or none (symmetric)."}
    return {"win": False, "matches": matches,
            "tier": f"No prize — {matches} matched",
            "prize": 0,
            "note": "Only 0/1/2/3/4 or 8/9/10/11/12 matches pay."}


# --------------------------------------------------------------------
# Pick 3
# --------------------------------------------------------------------

def _pick3_box_type(digits: Tuple[int, ...]) -> Optional[int]:
    """Number of unique permutations of the multiset. Returns None if all
    three digits are the same (can't be played as a valid box)."""
    c = Counter(digits)
    counts = sorted(c.values(), reverse=True)
    if counts == [3]:      return None    # 000, 111, ... — box invalid
    if counts == [2, 1]:   return 3
    if counts == [1, 1, 1]: return 6
    return None

PICK3_PLAY_TYPES = ["Straight", "Box", "Straight/Box", "Front Pair", "Back Pair"]

def check_pick3(user_digits: Tuple[int, ...], play_type: str,
                draw_digits: Tuple[int, ...],
                dollar_play: float = 1.0) -> Dict:
    """`dollar_play` = wager amount ($0.50 or $1). Prizes below are the
    Texas Lottery published $1-play amounts; the $0.50 play halves them."""
    scale = dollar_play / 1.0
    user = tuple(user_digits)
    draw = tuple(draw_digits)
    exact = user == draw
    same_multiset = sorted(user) == sorted(draw)
    bt = _pick3_box_type(user)
    prize = 0
    tier = "No prize"

    if play_type == "Straight":
        if exact:
            prize, tier = 500 * scale, "Straight — exact order match"
    elif play_type == "Box":
        if same_multiset and bt is not None:
            if bt == 3:
                prize, tier = 160 * scale, "Box 3-way — any order"
            else:
                prize, tier = 80 * scale, "Box 6-way — any order"
    elif play_type == "Straight/Box":
        # A $1 Straight/Box = 50¢ Straight + 50¢ Box
        if exact and bt is not None:
            straight_half = 250 * scale
            box_half = (80 if bt == 3 else 40) * scale
            prize = straight_half + box_half
            tier = f"Straight/Box — straight hit ({bt}-way)"
        elif same_multiset and bt is not None:
            prize = (80 if bt == 3 else 40) * scale
            tier = f"Straight/Box — box only ({bt}-way)"
    elif play_type == "Front Pair":
        if user[0] == draw[0] and user[1] == draw[1]:
            prize, tier = 50 * scale, "Front Pair — first two digits"
    elif play_type == "Back Pair":
        if user[1] == draw[1] and user[2] == draw[2]:
            prize, tier = 50 * scale, "Back Pair — last two digits"

    return {"win": prize > 0, "prize": prize, "tier": tier,
            "play_type": play_type, "user_digits": user,
            "draw_digits": draw,
            "note": ("Assumes $1 base play. Fireball / Sum It Up! not "
                     "modelled.")}


# --------------------------------------------------------------------
# Daily 4
# --------------------------------------------------------------------

def _daily4_box_type(digits: Tuple[int, ...]) -> Optional[int]:
    """Number of unique permutations. Returns None for all-same-digit."""
    c = Counter(digits)
    counts = sorted(c.values(), reverse=True)
    if counts == [4]:            return None
    if counts == [3, 1]:         return 4
    if counts == [2, 2]:         return 6
    if counts == [2, 1, 1]:      return 12
    if counts == [1, 1, 1, 1]:   return 24
    return None

DAILY4_PLAY_TYPES = ["Straight", "Box", "Straight/Box", "Front Pair", "Back Pair"]

_DAILY4_BOX_1DOLLAR = {4: 1250, 6: 833, 12: 416, 24: 208}
_DAILY4_HALFBOX = {4: 625, 6: 416, 12: 208, 24: 104}

def check_daily4(user_digits: Tuple[int, ...], play_type: str,
                 draw_digits: Tuple[int, ...],
                 dollar_play: float = 1.0) -> Dict:
    scale = dollar_play / 1.0
    user = tuple(user_digits)
    draw = tuple(draw_digits)
    exact = user == draw
    same_multiset = sorted(user) == sorted(draw)
    bt = _daily4_box_type(user)
    prize = 0
    tier = "No prize"

    if play_type == "Straight":
        if exact:
            prize, tier = 5000 * scale, "Straight — exact order match"
    elif play_type == "Box":
        if same_multiset and bt is not None:
            prize, tier = _DAILY4_BOX_1DOLLAR[bt] * scale, f"Box {bt}-way — any order"
    elif play_type == "Straight/Box":
        if exact and bt is not None:
            straight_half = 2500 * scale
            prize = straight_half + _DAILY4_HALFBOX[bt] * scale
            tier = f"Straight/Box — straight hit ({bt}-way)"
        elif same_multiset and bt is not None:
            prize = _DAILY4_HALFBOX[bt] * scale
            tier = f"Straight/Box — box only ({bt}-way)"
    elif play_type == "Front Pair":
        if user[0] == draw[0] and user[1] == draw[1]:
            prize, tier = 50 * scale, "Front Pair"
    elif play_type == "Back Pair":
        if user[2] == draw[2] and user[3] == draw[3]:
            prize, tier = 50 * scale, "Back Pair"

    return {"win": prize > 0, "prize": prize, "tier": tier,
            "play_type": play_type, "user_digits": user,
            "draw_digits": draw,
            "note": "Assumes $1 base play. Fireball / Sum It Up! not modelled."}


# --------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------

def check_ticket(game_name: str, user_main, draw_main,
                 user_bonus: Optional[int] = None,
                 draw_bonus: Optional[int] = None,
                 play_type: Optional[str] = None,
                 dollar_play: float = 1.0) -> Dict:
    g = GAMES[game_name]
    if g.game_type == "digit":
        if game_name == "Pick 3":
            return check_pick3(user_main, play_type, draw_main, dollar_play)
        return check_daily4(user_main, play_type, draw_main, dollar_play)
    if game_name == "All or Nothing":
        return check_all_or_nothing(user_main, draw_main)
    if g.bonus_n:
        return check_kn_bonus(user_main, user_bonus, draw_main, draw_bonus,
                              game_name)
    return check_simple_kn(user_main, draw_main, game_name)
