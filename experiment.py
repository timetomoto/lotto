"""Append-only experiment log for pre-registered 50-draw tracking.

The core integrity rule: once an entry is written, the sequence and metadata
are immutable. Scoring against future draws is a read-only operation that
produces derived data, never a mutation of the original entry.
"""
import json
import os
from datetime import datetime, date
from typing import List, Tuple, Dict, Optional

LOG_PATH = "experiment_log.json"

def _read_all() -> List[Dict]:
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH) as f:
        return json.load(f)

def _write_all(entries: List[Dict]) -> None:
    with open(LOG_PATH, "w") as f:
        json.dump(entries, f, indent=2, default=str)

def append_entry(game: str, strategy: str, sequence: Tuple[int, ...],
                 window_start_date: Optional[date], window_size: int,
                 notes: str = "", source_detail: str = "") -> Dict:
    entries = _read_all()
    entry = {
        "id": len(entries),
        "created_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "game": game,
        "strategy": strategy,
        "sequence": list(sequence),
        "window_start_date": window_start_date.isoformat() if window_start_date else None,
        "window_size": window_size,
        "source_detail": source_detail,
        "notes": notes,
    }
    entries.append(entry)
    _write_all(entries)
    return entry

def list_entries(game: Optional[str] = None) -> List[Dict]:
    entries = _read_all()
    if game:
        entries = [e for e in entries if e["game"] == game]
    return entries

def score_entry(entry: Dict, future_draws: List[Tuple[date, Tuple[int, ...]]]) -> Dict:
    """Score a locked sequence against draws that occurred on or after its window_start_date.
    Returns per-draw match list and cumulative total."""
    start = date.fromisoformat(entry["window_start_date"]) if entry["window_start_date"] else None
    seq_set = set(entry["sequence"])
    picked: List[Tuple[date, int]] = []
    for dt, nums in future_draws:
        if start is not None and dt < start:
            continue
        if len(picked) >= entry["window_size"]:
            break
        matches = len(seq_set & set(nums))
        picked.append((dt, matches))
    per_draw = [m for _, m in picked]
    return {"per_draw": per_draw, "dates": [d.isoformat() for d, _ in picked],
            "cumulative": _cumsum(per_draw), "n_scored": len(per_draw),
            "total_matches": sum(per_draw)}

def _cumsum(xs: List[int]) -> List[int]:
    out = []
    s = 0
    for x in xs:
        s += x
        out.append(s)
    return out
