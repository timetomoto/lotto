"""Static how-to-play and prize-tier info per game.

Sourced from texaslottery.com game pages (verified 2026-07-10). Prize amounts
for the jackpot / top tiers roll or vary by drawing; the values shown here
reflect what the site displayed at retrieval time. Odds and lower-tier
amounts are the fixed structural values published by the Texas Lottery.
"""
from typing import List, Tuple, Dict

GAME_INFO: Dict[str, Dict] = {
    "Lotto Texas": {
        "how_to_play": (
            "Pick 6 numbers from 1–54, or use Quick Pick. $1 per play. "
            "Optional Extra! add-on ($1 more) boosts non-jackpot prizes "
            "up to $10,000 and unlocks a 2-of-6 payout."
        ),
        "prize_tiers": [
            ("6 of 6",  "Jackpot (starts at $5M, rolls if no winner)"),
            ("5 of 6",  "~$1,239 (varies by drawing)"),
            ("4 of 6",  "~$38"),
            ("3 of 6",  "$3"),
            ("2 of 6",  "$2 (Extra! only)"),
        ],
        "odds_note": "Overall odds ~1 in 71.",
    },
    "Mega Millions": {
        "how_to_play": (
            "Pick 5 numbers from 1–70 plus 1 Mega Ball from 1–24. "
            "$5 per play (includes built-in 2×–10× multiplier on "
            "non-jackpot prizes). Multi-state game."
        ),
        "prize_tiers": [
            ("5 + Mega Ball",  "Jackpot (starts $20M, rolls)"),
            ("5",              "$1,000,000"),
            ("4 + Mega Ball",  "$10,000"),
            ("4",              "$500"),
            ("3 + Mega Ball",  "$200"),
            ("3",              "$10"),
            ("2 + Mega Ball",  "$10"),
            ("1 + Mega Ball",  "$7"),
            ("0 + Mega Ball",  "$5"),
        ],
        "odds_note": "Overall odds ~1 in 23. Non-jackpot prizes ×multiplier.",
    },
    "Powerball": {
        "how_to_play": (
            "Pick 5 numbers from 1–69 plus 1 Powerball from 1–26. "
            "$2 per play. Optional Power Play add-on ($1 more) multiplies "
            "non-jackpot prizes by 2×–10×. Multi-state game."
        ),
        "prize_tiers": [
            ("5 + Powerball",  "Jackpot (starts $20M, rolls)"),
            ("5",              "$1,000,000"),
            ("4 + Powerball",  "$50,000"),
            ("4",              "$100"),
            ("3 + Powerball",  "$100"),
            ("3",              "$7"),
            ("2 + Powerball",  "$7"),
            ("1 + Powerball",  "$4"),
            ("0 + Powerball",  "$4"),
        ],
        "odds_note": "Overall odds ~1 in 25.",
    },
    "Cash Five": {
        "how_to_play": (
            "Pick 5 numbers from 1–35, or use Quick Pick. $1 per play. "
            "Drawings six nights a week (Mon–Sat)."
        ),
        "prize_tiers": [
            ("5 of 5",  "$25,000 (fixed top prize)"),
            ("4 of 5",  "$350"),
            ("3 of 5",  "$15"),
            ("2 of 5",  "Free Cash Five ticket"),
        ],
        "odds_note": "Overall odds ~1 in 8.",
    },
    "Texas Two Step": {
        "how_to_play": (
            "Pick 4 numbers from 1–35 plus 1 Bonus Ball from a separate 1–35. "
            "$1 per play. Drawings Monday and Thursday."
        ),
        "prize_tiers": [
            ("4 + Bonus",  "Jackpot (starts $200K, rolls)"),
            ("4",          "~$1,638 (varies)"),
            ("3 + Bonus",  "$50"),
            ("3",          "~$19"),
            ("2 + Bonus",  "~$21"),
            ("1 + Bonus",  "$7"),
            ("0 + Bonus",  "$5"),
        ],
        "odds_note": "Overall odds ~1 in 32.",
    },
    "All or Nothing": {
        "how_to_play": (
            "Pick 12 numbers from 1–24. Win the top prize by matching "
            "**all 12** — or **none of them at all**. $2 per play, four "
            "draws a day (morning, day, evening, night), Mon–Sat."
        ),
        "prize_tiers": [
            ("All 12 or 0 matches",  "$250,000 (top prize)"),
            ("11 or 1",              "$500"),
            ("10 or 2",              "$50"),
            ("9 or 3",               "$10"),
            ("8 or 4",               "$2"),
        ],
        "odds_note": "Overall odds ~1 in 4.5 (many low-tier winners).",
    },
    "Pick 3": {
        "how_to_play": (
            "Pick 3 digits (0–9 each) and a play type: Straight (exact "
            "order), Box (any order), Straight/Box, Combo, or Pair. "
            "Plays $0.50–$5. Four draws daily (Mon–Sat). Optional Fireball "
            "add-on adds a wild-digit chance."
        ),
        "prize_tiers": [
            ("Straight (exact) — $1 play",  "$500"),
            ("Box 3-way (any order)",       "$160"),
            ("Box 6-way (any order)",       "$80"),
            ("Straight/Box (both hit)",     "$330"),
            ("Front Pair or Back Pair",     "$50"),
        ],
        "odds_note": "Straight odds: 1 in 1,000. Box odds vary by play type.",
    },
    "Daily 4": {
        "how_to_play": (
            "Pick 4 digits (0–9 each) and a play type: Straight, Box, "
            "Straight/Box, Combo, or Pair. Plays $0.50–$5. Four draws "
            "daily (Mon–Sat). Optional Fireball add-on."
        ),
        "prize_tiers": [
            ("Straight (exact) — $1 play",  "$5,000"),
            ("Box 4-way",                   "$1,250"),
            ("Box 6-way",                   "$833"),
            ("Box 12-way",                  "$416"),
            ("Box 24-way",                  "$208"),
            ("Front Pair or Back Pair",     "$50"),
        ],
        "odds_note": "Straight odds: 1 in 10,000.",
    },
}
