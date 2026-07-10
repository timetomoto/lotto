"""Texas Lottery Randomness Auditor — local Streamlit app.

Run: `streamlit run app.py`
Open the URL Streamlit prints (default http://localhost:8501).
"""
from __future__ import annotations
from datetime import date
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from games import GAMES, GameConfig
from loader import load_draws, filter_era, load_bonus_ball, load_draws_full
from checker import (check_ticket, PICK3_PLAY_TYPES, DAILY4_PLAY_TYPES)
from strategies import (
    frequency_counter, per_position_counters,
    s1_most_frequent, s4_least_frequent, s2_prng, s3_qrng,
    most_frequent_bonus, top_bonus_by_frequency,
)
from stats_tests import (
    chi_square_ball_frequency, chi_square_per_position_digit,
    chi_square_per_position_kn,
    chi_square_bonus_ball, paired_permutation_test, null_band_for_matches,
    historical_match_distribution, walk_forward_backtest,
    ljung_box_per_ball, runs_test_draw_sums, gap_test_aggregate,
    pair_cooccurrence_aggregate, cusum_drift_aggregate, rolling_frequency,
    holm_correction,
)
from mc_null import (
    mc_walk_forward_null, mc_walk_forward_pvalue,
    mc_serial_dependence_null, mc_gap_test_null,
    mc_pair_cooccurrence_null, mc_cusum_drift_null,
)
import os
from qrng import load_or_pull
import experiment
import draw_schedule as sched
from draw_schedule import next_draw_datetime, draws_for_day, CT
from game_info import GAME_INFO
import streamlit.components.v1 as components
from datetime import datetime, timedelta

st.set_page_config(
    page_title="Texas Lottery Randomness Auditor",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ------------------------------------------------------------------
# Auto-refresh-if-stale — kick off download_data.sh once per session
# if the newest CSV on disk is more than STALE_HOURS old. Failure is
# silent (falls back to whatever's on disk — either git-committed
# baseline or the last successful refresh in this container).
# ------------------------------------------------------------------

STALE_HOURS = 24

# ------------------------------------------------------------------
# Draw-time display helpers — static "Next draw: ..." + live countdown
# ------------------------------------------------------------------

COUNTDOWN_WINDOW_MIN = 60   # switch from static to live countdown when
                            # the next draw is within this many minutes

def _fmt_draw_static(dt: datetime, now_ct: datetime) -> str:
    """Short human string like 'today 10:12 PM CT' or 'Fri Jul 17 10:12 PM CT'."""
    same_day = dt.date() == now_ct.date()
    tomorrow = dt.date() == (now_ct.date() + timedelta(days=1))
    tm = dt.strftime("%-I:%M %p")
    if same_day:
        prefix = "today"
    elif tomorrow:
        prefix = "tomorrow"
    else:
        prefix = dt.strftime("%a %b %-d")
    return f"{prefix} {tm} CT"

def _countdown_html(dt: datetime, label: str = "Next draw") -> str:
    """Live-updating JS countdown to `dt`. Rendered inside a components.html
    iframe so its <script> can execute."""
    target_iso = dt.isoformat()
    return f"""
<!doctype html><html><body style='margin:0;padding:0;font-family:
  -apple-system, "Segoe UI", sans-serif;color:#eee;background:transparent;'>
<div style='font-size:0.85rem;padding:2px 0;'>
  <span style='opacity:0.75;'>{label}:</span>
  <b id='cd' style='color:#ffcc00;'>—</b>
  <span style='opacity:0.6;font-size:0.8em;'>({dt.strftime("%-I:%M %p")} CT)</span>
</div>
<script>
  (function() {{
    const target = new Date("{target_iso}").getTime();
    const el = document.getElementById("cd");
    function tick() {{
      const diff = target - Date.now();
      if (diff <= 0) {{ el.textContent = "drawing now"; return; }}
      const m = Math.floor(diff / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      el.textContent = m + "m " + String(s).padStart(2, "0") + "s";
    }}
    tick(); setInterval(tick, 1000);
  }})();
</script></body></html>"""

def render_next_draw(game_cfg, now_ct: datetime | None = None) -> None:
    """Render the next-draw line for a game. Static text if the draw is more
    than COUNTDOWN_WINDOW_MIN minutes away; live-updating countdown widget
    otherwise. No-op for games without configured draw_times."""
    if now_ct is None:
        now_ct = datetime.now(CT)
    dt = next_draw_datetime(game_cfg, now_ct)
    if dt is None:
        return
    minutes = (dt - now_ct).total_seconds() / 60.0
    if minutes <= COUNTDOWN_WINDOW_MIN:
        components.html(_countdown_html(dt), height=32)
    else:
        st.markdown(
            f"<div style='font-size:0.85rem;opacity:0.75;"
            f"margin-top:0.1rem;'>Next draw: <b>{_fmt_draw_static(dt, now_ct)}"
            f"</b></div>",
            unsafe_allow_html=True,
        )

def _maybe_auto_refresh() -> None:
    if st.session_state.get("_auto_refresh_ran"):
        return
    st.session_state["_auto_refresh_ran"] = True
    import glob, subprocess, pathlib, time as _time
    csvs = glob.glob("data/*.csv")
    if not csvs:
        return
    newest = max(os.path.getmtime(p) for p in csvs)
    if (_time.time() - newest) / 3600.0 < STALE_HOURS:
        return
    script = pathlib.Path(__file__).parent / "download_data.sh"
    if not script.exists():
        return
    try:
        subprocess.run(["bash", str(script)], capture_output=True,
                       timeout=90, check=False)
        st.cache_data.clear()
    except Exception:
        pass  # keep serving what's on disk

_maybe_auto_refresh()

# Global styling — heading spacing + right-align the last 3 tabs
# (Audit / Experiment / Methods) to visually separate the analytical
# section from the user-facing one (Overview / Schedule / Check Numbers).
st.markdown(
    """
    <style>
      /* Give h3/h4 headings breathing room from the preceding content */
      div[data-testid="stMarkdownContainer"] h3 { margin-top: 1.9rem !important; }
      div[data-testid="stMarkdownContainer"] h4 { margin-top: 1.4rem !important; }
      div[data-testid="stMarkdownContainer"] p:has(strong:first-child) {
          margin-top: 1.1rem;
      }
      /* Tab split — push the 4th tab and everything after it to the right */
      div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-child(4) {
          margin-left: auto;
      }
      /* Overview cards live inside stColumn — Streamlit's default 1rem
         margin on every stElementContainer stacks up between st.markdown /
         st.image / st.dataframe calls and inflates card height. Compress
         it here (scoped to columns so audit/experiment metrics elsewhere
         keep their default spacing). */
      div[data-testid="stColumn"] div[data-testid="stElementContainer"],
      div[data-testid="stColumn"] .stElementContainer,
      div[data-testid="stColumn"] .element-container {
          margin-top: 0.1rem !important;
          margin-bottom: 0.1rem !important;
      }
      /* Tighten the specific gap between the banner image and the title
         below it. Streamlit's stImage wrapper adds its own padding, and
         the h3 has default block-margin from user-agent CSS that our
         scoped rule above doesn't fully suppress. */
      div[data-testid="stColumn"] div[data-testid="stImage"] {
          margin-bottom: 0 !important;
          padding-bottom: 0 !important;
      }
      div[data-testid="stColumn"] div[data-testid="stImage"] figure,
      div[data-testid="stColumn"] div[data-testid="stImage"] img {
          margin-bottom: 0 !important;
      }
      div[data-testid="stColumn"] h3 {
          margin-top: 0.25rem !important;
          margin-bottom: 0.2rem !important;
          padding-top: 0 !important;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# Cached data loaders — keyed on file mtime so cron writes invalidate cache
# ------------------------------------------------------------------

def _csv_signature(game_key: str) -> tuple:
    g = GAMES[game_key]
    return tuple(os.path.getmtime(p) if os.path.exists(p) else 0.0
                 for p in g.csv_paths)

@st.cache_data
def _get_draws_cached(game_key: str, sig: tuple):
    g = GAMES[game_key]
    all_draws = load_draws(g)
    era_draws = filter_era(all_draws, g)
    return all_draws, era_draws

def get_draws(game_key: str):
    return _get_draws_cached(game_key, _csv_signature(game_key))

@st.cache_data
def _get_bonus_cached(game_key: str, sig: tuple):
    return load_bonus_ball(GAMES[game_key])

def get_bonus_values(game_key: str):
    """Era-filtered bonus-ball values; empty list if game has no bonus pool."""
    if not GAMES[game_key].bonus_n:
        return []
    return _get_bonus_cached(game_key, _csv_signature(game_key))

@st.cache_data
def _get_walk_forward_cached(game_key: str, sig: tuple, burn_in: int):
    g = GAMES[game_key]
    _, era = _get_draws_cached(game_key, sig)
    return walk_forward_backtest(era, g, burn_in=burn_in)

def get_walk_forward(game_key: str, burn_in: int = 50):
    return _get_walk_forward_cached(game_key, _csv_signature(game_key), burn_in)

@st.cache_data
def get_qrng_stream():
    return load_or_pull()

# ------------------------------------------------------------------
# Header
# ------------------------------------------------------------------

header_l, header_r = st.columns([4, 1])
with header_l:
    st.title("Texas Lottery Randomness Auditor")
    st.caption(
        "A falsification-experiment thesis artifact — not a lottery "
        "predictor. Each game is filtered to the earliest date the current "
        "format has been continuously in effect (see Methods)."
    )
with header_r:
    # Data freshness + one-click refresh
    latest_dt = max(
        (get_draws(name)[1][-1][0] for name in GAMES if get_draws(name)[1]),
        default=None,
    )
    st.markdown(
        f"<div style='text-align:right;padding-top:0.4rem;'>"
        f"<small>Data through</small><br>"
        f"<b>{latest_dt.strftime('%b %d, %Y') if latest_dt else 'no data'}</b>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if st.button("↻ Refresh now", width="stretch"):
        import subprocess, pathlib
        script = pathlib.Path(__file__).parent / "download_data.sh"
        with st.spinner("Downloading latest CSVs from Texas Lottery..."):
            try:
                r = subprocess.run(["bash", str(script)], capture_output=True,
                                   text=True, timeout=60)
                if r.returncode == 0:
                    st.cache_data.clear()
                    st.success("Data refreshed.")
                    st.rerun()
                else:
                    st.error(f"Refresh failed: {r.stderr[-500:]}")
            except subprocess.TimeoutExpired:
                st.error("Refresh timed out after 60s.")

(tab_overview, tab_schedule, tab_check, tab_audit,
 tab_experiment, tab_methods) = st.tabs(
    ["Overview", "Schedule", "Check Numbers", "Audit",
     "Experiment", "Methods"]
)

# ==================================================================
# Overview — one card per game
# ==================================================================

def _format_recent_line(draw_date, nums, s1, game_type):
    """One row of the recent-draws list. Matches vs S1 are bold green.
    - kn:    highlight ball if it's in the S1 set.
    - digit: highlight digit at position i if it equals s1[i].
    Returns a raw HTML fragment (no <p>/<small> wrapper) so callers can pack
    multiple rows into a single tight container. Numbers use explicit CSS
    margin (not &nbsp;) so horizontal spacing is even and adjustable."""
    s1_set = set(s1)
    parts = []
    for i, n in enumerate(nums):
        if game_type == "kn":
            hit = n in s1_set
        else:
            hit = i < len(s1) and n == s1[i]
        if hit:
            parts.append(
                f"<b style='color:#22c55e;margin-right:0.75rem;'>{n}</b>"
            )
        else:
            parts.append(
                f"<span style='color:#8a8a8a;margin-right:0.75rem;'>{n}</span>"
            )
    date_label = draw_date.strftime("%m/%d/%y")
    return (f"<span style='color:#8a8a8a;margin-right:1rem;'>"
            f"{date_label}</span>" + "".join(parts))

def _seq_pretty(seq, game_type):
    """Format an S1/S4 sequence for display. For digit games, label positions
    so it's clear a shared digit across S1/S4 is *positional* — not a
    contradiction."""
    if game_type == "digit":
        return "  ".join(f"pos {i}: `{n}`" for i, n in enumerate(seq))
    return "  ".join(f"`{n:>2}`" for n in seq)

def render_overview_card(g_name: str):
    g_cfg = GAMES[g_name]
    _, era_d = get_draws(g_name)
    s1 = s1_most_frequent(era_d, g_cfg)
    s4 = s4_least_frequent(era_d, g_cfg)

    fmt = f"{g_cfg.k_main}-of-{g_cfg.n_main}"
    if g_cfg.game_type == "digit":
        fmt = f"{g_cfg.k_main} digits (0–{g_cfg.n_main - 1})"

    # Official Texas Lottery banner image at the top of the card. All 8
    # images are manually normalized to 355×169; rendered at native size
    # (no stretching, no upscaling). Small negative top-margin + inline h3
    # with tight top-margin tightens the image→title spacing that
    # Streamlit's default h3 margin would otherwise create.
    img_path = f"data/images/{g_name.lower().replace(' ', '_')}.png"
    if os.path.exists(img_path):
        st.markdown("<div style='margin-top:0.2rem;'></div>",
                    unsafe_allow_html=True)
        st.image(img_path, width=355)

    # Title is a link to the official Texas Lottery page for the game.
    # URL slug is game name with spaces → underscores; matches the same
    # convention the site itself uses (verified against all 8 games).
    tx_url = ("https://www.texaslottery.com/export/sites/lottery/Games/"
              f"{g_name.replace(' ', '_')}/index.html")
    st.markdown(
        f"<h3 style='margin-top:0.35rem !important;margin-bottom:0.2rem;'>"
        f"<a href='{tx_url}' target='_blank' rel='noopener' "
        f"style='color:inherit;text-decoration:none;'>"
        f"{g_name}"
        f"<span style='font-size:0.6em;opacity:0.55;margin-left:0.4em;'>"
        f"↗</span>"
        f"</a></h3>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{fmt} · {g_cfg.schedule} · {g_cfg.ticket_cost} · "
        f"{len(era_d):,} draws since {g_cfg.era_start.strftime('%b %Y')}"
    )
    render_next_draw(g_cfg)
    st.markdown("**Most-frequent (S1)**")
    if g_cfg.game_type == "digit":
        seq_html = " &nbsp; ".join(
            f"<span style='opacity:0.55;font-size:0.7em;'>pos&nbsp;{i}</span>&nbsp;<code>{n}</code>"
            for i, n in enumerate(s1)
        )
        st.markdown(
            f"<div style='font-size:1.25rem;font-family:monospace;"
            f"white-space:nowrap;overflow-x:auto;padding:0.2rem 0;'>"
            f"{seq_html}</div>",
            unsafe_allow_html=True,
        )
        st.caption("Positional — most-frequent digit at each position.")
    else:
        # Size scales with K so the sequence always fits on one line in a
        # 3-column card. K=4..6 fits comfortably at 1.7rem; K=12 needs ~1rem.
        font_rem = max(0.95, 1.8 - 0.07 * len(s1))
        seq_html = " ".join(f"<code>{n:>2}</code>" for n in s1)
        st.markdown(
            f"<div style='font-size:{font_rem:.2f}rem;font-weight:600;"
            f"font-family:monospace;white-space:nowrap;overflow-x:auto;"
            f"padding:0.2rem 0;'>{seq_html}</div>",
            unsafe_allow_html=True,
        )

    # Most-frequent bonus ball (games with a separate bonus pool that ships
    # with the base ticket — Mega Ball, Powerball, Bonus Ball). One small
    # line, no new claim; the argmax comes from the same tally that already
    # feeds the bonus-pool audit.
    if g_cfg.bonus_n:
        top_bonus = most_frequent_bonus(g_cfg, get_bonus_values(g_name))
        if top_bonus is not None:
            st.markdown(
                f"<div style='font-size:0.9rem;opacity:0.85;"
                f"margin-top:0.2rem;'>"
                f"+ Most-frequent <b>{g_cfg.bonus_label}</b>: "
                f"<code>{top_bonus}</code>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Most-frequent Numbers — the next-K balls (or per-position runners-up)
    # ranked just below S1. Visually secondary to S1.
    if g_cfg.game_type == "kn":
        counter = frequency_counter(era_d)
        ranked = sorted(range(1, g_cfg.n_main + 1),
                        key=lambda b: (-counter.get(b, 0), b))
        runners = ranked[g_cfg.k_main:2 * g_cfg.k_main]
        st.markdown("**Most-frequent Numbers** _(next after S1)_")
        seq_html = " ".join(f"<code>{n:>2}</code>" for n in sorted(runners))
        st.markdown(
            f"<div style='font-size:1.0rem;font-family:monospace;"
            f"white-space:nowrap;overflow-x:auto;opacity:0.75;"
            f"padding:0.15rem 0;'>{seq_html}</div>",
            unsafe_allow_html=True,
        )
    else:
        per_pos = per_position_counters(era_d, g_cfg.k_main)
        runners = []
        for pos_c in per_pos:
            ranked = sorted(range(g_cfg.n_main),
                            key=lambda d: (-pos_c.get(d, 0), d))
            runners.append(ranked[1])
        st.markdown("**Most-frequent Numbers** _(runner-up per position)_")
        seq_html = " &nbsp; ".join(
            f"<span style='opacity:0.55;font-size:0.7em;'>pos&nbsp;{i}</span>"
            f"&nbsp;<code>{n}</code>"
            for i, n in enumerate(runners)
        )
        st.markdown(
            f"<div style='font-size:1.0rem;font-family:monospace;"
            f"white-space:nowrap;overflow-x:auto;opacity:0.75;"
            f"padding:0.15rem 0;'>{seq_html}</div>",
            unsafe_allow_html=True,
        )

    # Second most-frequent bonus ball for games with a bonus pool. Placed
    # immediately below the runners-up section to mirror the top-bonus
    # line under S1.
    if g_cfg.bonus_n:
        top2 = top_bonus_by_frequency(g_cfg, get_bonus_values(g_name), k=2)
        if len(top2) >= 2:
            st.markdown(
                f"<div style='font-size:0.9rem;opacity:0.75;"
                f"margin-top:0.2rem;'>"
                f"+ 2nd most-frequent <b>{g_cfg.bonus_label}</b>: "
                f"<code>{top2[1]}</code>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # Pack all 5 rows into a single tight container so each row's line-height
    # is controlled directly (avoids Streamlit's default paragraph margins).
    recent_rows_html = "".join(
        f"<div style='line-height:1.5;font-size:0.88rem;'>"
        f"{_format_recent_line(dt, nums, s1, g_cfg.game_type)}"
        f"</div>"
        for dt, nums in reversed(era_d[-5:])
    )
    st.markdown(
        f"<div style='margin-top:1rem;margin-bottom:1.1rem;'>"
        f"<b>Last 5 draws</b> "
        f"<span style='opacity:0.7;'>(matches vs S1 in green)</span>"
        f"<div style='margin-top:0.35rem;'>{recent_rows_html}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    # Walk-forward backtest: at each historical draw t (past a 50-draw
    # burn-in), derive S1 from *only* draws before t and score against
    # draw t. This is an honest out-of-sample test — ticket and draw are
    # independent by construction.
    wf = get_walk_forward(g_name, burn_in=50)
    n_scored = wf["n_scored"]
    if g_cfg.game_type == "kn":
        obs_3plus = sum(wf["obs_counts"][3:])
        exp_3plus = sum(wf["exp_counts"][3:])
        st.caption(
            f"**Walk-forward backtest** (out-of-sample): using only draws "
            f"prior to each date, S1 matched **3 or more** balls in "
            f"**{obs_3plus:,} of {n_scored:,}** subsequent draws "
            f"({obs_3plus / n_scored * 100:.2f}%). Expected under H₀ "
            f"(fair lottery): ~{exp_3plus:.1f} draws "
            f"({exp_3plus / n_scored * 100:.2f}%)."
        )
    else:
        obs_exact = wf["obs_counts"][g_cfg.k_main]
        exp_exact = wf["exp_counts"][g_cfg.k_main]
        st.caption(
            f"**Walk-forward backtest** (out-of-sample): the prevailing S1 "
            f"was an **exact match** in **{obs_exact:,} of {n_scored:,}** "
            f"subsequent draws. Expected under H₀: ~{exp_exact:.1f}."
        )

    info = GAME_INFO.get(g_name)
    if info:
        with st.expander("How to play & prizes"):
            st.markdown("**How to play**")
            st.write(info["how_to_play"])
            st.markdown("**Prize tiers**")
            st.dataframe(
                pd.DataFrame(info["prize_tiers"], columns=["Match", "Prize"]),
                width="stretch", hide_index=True,
            )
            if info.get("odds_note"):
                st.caption(info["odds_note"])

    # Bottom margin of the card — takes the place of the space that used
    # to sit above (reversed relative to before).
    st.markdown("<div style='margin-bottom:2rem;'></div>",
                unsafe_allow_html=True)

with tab_overview:
    st.subheader("All Texas Lottery non-scratch games")
    st.caption(
        "For each game, the sequence shown is the K balls (or digits) that "
        "appeared most frequently in the game's current-format history. "
        "**These are not predictions.** They're candidate sequences for the "
        "falsification experiment in the Experiment tab."
    )

    game_names = list(GAMES.keys())
    per_row = 3
    for row_start in range(0, len(game_names), per_row):
        cols = st.columns(per_row)
        for col, g_name in zip(cols, game_names[row_start:row_start + per_row]):
            with col:
                render_overview_card(g_name)
        st.markdown("")

# ==================================================================
# Schedule — upcoming draws
# ==================================================================

with tab_schedule:
    st.subheader("Upcoming draws — the next two weeks")
    st.write(
        "A day-by-day plan showing which games draw when, the current "
        "candidate sequence (S1) for each, and the minimum single-play cost. "
        "This is *not* a purchasing recommendation — under H₀ these "
        "sequences are no more likely to win than any other pick. It is a "
        "practical schedule if you choose to run the tracking experiment."
    )

    horizon = st.slider("Days ahead", min_value=3, max_value=28, value=14, step=1)
    upcoming = sched.upcoming_draws(days_ahead=horizon, include_inactive=True)

    # Group by day
    from collections import defaultdict
    by_day = defaultdict(list)
    for row in upcoming:
        by_day[row["date"]].append(row)

    # Compute S1 per game once
    game_s1 = {name: s1_most_frequent(get_draws(name)[1], GAMES[name])
               for name in GAMES}

    total_horizon_cost = 0.0
    total_draws_planned = 0

    def _grey_inactive_rows(row):
        """Pandas Styler callback — apply muted styling to inactive rows."""
        if row.get("_active", True):
            return [""] * len(row)
        return ["color: #999; font-style: italic;"] * len(row)

    for dt in sorted(by_day.keys()):
        day_rows = by_day[dt]
        active_rows = [r for r in day_rows if r["active"]]
        day_cost = sum(r["cost_low"] * r["draws_per_day"] for r in active_rows)
        day_draws = sum(r["draws_per_day"] for r in active_rows)
        n_active = len(active_rows)
        total_horizon_cost += day_cost
        total_draws_planned += day_draws
        st.markdown(
            f"#### {dt.strftime('%a, %b %d')} "
            f"— {n_active} game{'s' if n_active != 1 else ''} drawing, "
            f"{day_draws} draw{'s' if day_draws != 1 else ''}, "
            f"min. ${day_cost:.2f}"
        )
        # If any game has a draw within the countdown window today, surface
        # the soonest one as a live-updating widget above the table.
        now_ct = datetime.now(CT)
        if dt == now_ct.date():
            imminent = []
            for g_name, g in GAMES.items():
                nd = next_draw_datetime(g, now_ct)
                if nd is not None and nd.date() == dt:
                    minutes = (nd - now_ct).total_seconds() / 60.0
                    if 0 <= minutes <= COUNTDOWN_WINDOW_MIN:
                        imminent.append((nd, g_name))
            if imminent:
                imminent.sort()
                soonest_dt, soonest_game = imminent[0]
                components.html(
                    _countdown_html(soonest_dt,
                                    label=f"Next up: {soonest_game}"),
                    height=32,
                )

        rows = []
        for r in day_rows:
            g = GAMES[r["game"]]
            s1 = game_s1[r["game"]]
            if g.game_type == "digit":
                seq_str = "  ".join(f"pos {i}:{n}" for i, n in enumerate(s1))
            else:
                seq_str = " ".join(str(n) for n in s1)
            per_day = r["draws_per_day"]
            if r["active"]:
                daily_val = str(per_day)
                cost_str = (f"${r['cost_low']:.2f} × {per_day} = "
                            f"${r['cost_low'] * per_day:.2f}"
                            if per_day > 1 else f"${r['cost_low']:.2f}")
                times_str = " · ".join(
                    datetime.strptime(t, "%H:%M").strftime("%-I:%M %p")
                    for t in g.draw_times
                )
            else:
                daily_val = "—"
                cost_str = "—"
                times_str = "—"
            rows.append({
                "Game": r["game"],
                "Candidate (S1)": seq_str,
                "Daily draws": daily_val,
                "Times (CT)": times_str,
                "Min cost": cost_str,
                "_active": r["active"],  # hidden helper for styling
            })
        df_day = pd.DataFrame(rows)
        styled = (df_day.style
                  .apply(_grey_inactive_rows, axis=1)
                  .hide(subset=["_active"], axis="columns"))
        st.dataframe(styled, width="stretch", hide_index=True)

    st.divider()
    st.markdown(
        f"**Total across the next {horizon} days:** {total_draws_planned} "
        f"scheduled draws · **minimum spend ~${total_horizon_cost:.2f}** "
        f"(one ticket per draw at the base ticket price). "
        f"Actual cost is higher with multi-draw plays or add-ons like "
        f"Extra!, Power Play, Megaplier, or Fireball."
    )
    st.caption(
        "Times of day for morning/day/evening/night draws (All or Nothing, "
        "Pick 3, Daily 4) follow the Texas Lottery's published cadence — "
        "check the retailer's ticket for exact cutoff times per drawing."
    )

# ==================================================================
# Check Numbers — verify a ticket against a specific historical draw
# ==================================================================

with tab_check:
    st.subheader("Check numbers against a specific draw")
    st.write(
        "Pick a game, choose the exact draw you want to check against, "
        "enter your ticket numbers, and click **Check**. Prize amounts "
        "reflect the Texas Lottery's published fixed-tier payouts; jackpot "
        "and pari-mutuel tiers are labeled but not given a specific dollar "
        "amount (they vary per drawing — check the official winners page "
        "for the exact draw)."
    )

    check_game = st.selectbox(
        "Game", list(GAMES.keys()), key="check_game")
    check_g = GAMES[check_game]

    # Load draws with slot/bonus metadata; restrict the date selector to
    # real draw dates for this game.
    @st.cache_data
    def _load_full(game_key: str, sig: tuple):
        return load_draws_full(GAMES[game_key])

    full_rows = _load_full(check_game, _csv_signature(check_game))
    if not full_rows:
        st.info("No historical draws available for this game.")
        st.stop()

    # Build human-readable option labels
    def _draw_label(r):
        s = f"{r['date'].strftime('%a %Y-%m-%d')}"
        if r["slot"]:
            s += f" · {r['slot']}"
        s += f"  →  {'-'.join(str(n) for n in r['main'])}"
        if r["bonus"] is not None:
            s += f"  (+ {r['bonus']})"
        return s

    # Recent-first, cap to last 300 to keep the selectbox usable
    recent = list(reversed(full_rows))[:300]
    labels = [_draw_label(r) for r in recent]
    idx = st.selectbox(
        "Draw to check against",
        range(len(recent)),
        format_func=lambda i: labels[i],
        key="check_draw_idx",
    )
    chosen = recent[idx]

    # -------- Game-specific input widgets --------
    st.markdown("**Your ticket**")

    def _parse_int_list(s: str) -> list:
        try:
            return [int(x.strip()) for x in s.replace(",", " ").split()
                    if x.strip()]
        except ValueError:
            return []

    user_main = None
    user_bonus = None
    play_type = None
    dollar_play = 1.0
    input_ok = False
    err = None

    if check_g.game_type == "digit":
        col_a, col_b = st.columns([2, 1])
        with col_a:
            digits_str = st.text_input(
                f"Enter {check_g.k_main} digits (0–9), in order",
                placeholder=", ".join(["1"] * check_g.k_main),
                key="check_digits",
            )
        with col_b:
            play_type = st.selectbox(
                "Play type",
                PICK3_PLAY_TYPES if check_game == "Pick 3"
                else DAILY4_PLAY_TYPES,
                key="check_play_type",
            )
            dollar_play = st.radio(
                "Wager", [1.0, 0.5],
                format_func=lambda v: f"${v:.2f}",
                horizontal=True,
                key="check_wager",
            )
        digits = _parse_int_list(digits_str)
        if len(digits) == check_g.k_main and all(0 <= d <= 9 for d in digits):
            user_main = tuple(digits)
            input_ok = True
        elif digits_str.strip():
            err = f"Enter exactly {check_g.k_main} digits between 0 and 9."
    else:
        # k-of-N game (with or without bonus)
        col_a, col_b = st.columns([3, 1])
        with col_a:
            main_str = st.text_input(
                f"Enter {check_g.k_main} numbers (1–{check_g.n_main}), "
                f"comma or space separated",
                placeholder=", ".join(str(i) for i in range(1, check_g.k_main + 1)),
                key="check_main",
            )
        if check_g.bonus_n:
            with col_b:
                user_bonus = st.number_input(
                    f"{check_g.bonus_label} (1–{check_g.bonus_n})",
                    min_value=1, max_value=int(check_g.bonus_n), step=1,
                    value=1, key="check_bonus",
                )
        picks = _parse_int_list(main_str)
        if (len(picks) == check_g.k_main
                and len(set(picks)) == check_g.k_main
                and all(1 <= p <= check_g.n_main for p in picks)):
            user_main = set(picks)
            input_ok = True
        elif main_str.strip():
            err = (f"Enter exactly {check_g.k_main} DISTINCT numbers "
                   f"between 1 and {check_g.n_main}.")

    if err:
        st.error(err)

    submitted = st.button("Check", type="primary", disabled=not input_ok)

    @st.dialog("Ticket result")
    def _result_dialog(result, game_cfg, chosen_draw, user_main_disp,
                       user_bonus_disp):
        # Draw & pick summary strings
        draw_str = "-".join(str(n) for n in chosen_draw["main"])
        if chosen_draw["bonus"] is not None:
            draw_str += f"  (+ {chosen_draw['bonus']} {game_cfg.bonus_label})"
        if game_cfg.game_type == "digit":
            pick_str = "-".join(str(n) for n in user_main_disp)
        else:
            pick_str = ", ".join(str(n) for n in sorted(user_main_disp))
        if user_bonus_disp is not None:
            pick_str += f"  (+ {user_bonus_disp} {game_cfg.bonus_label})"

        c1, c2 = st.columns(2)
        c1.markdown(f"**Draw:** `{draw_str}`  \n"
                    f"**Date:** {chosen_draw['date']}"
                    + (f"  \n**Slot:** {chosen_draw['slot']}"
                       if chosen_draw['slot'] else ""))
        c2.markdown(f"**Your ticket:** `{pick_str}`  \n"
                    + (f"**Play type:** {result.get('play_type','')}"
                       if game_cfg.game_type == "digit"
                       else (f"**Matches:** {result['matches']} of "
                             f"{game_cfg.k_main}"
                             + (f" + bonus"
                                if result.get("bonus_match") else ""))))

        st.divider()

        if result["win"]:
            prize = result["prize"]
            if isinstance(prize, (int, float)) and prize > 0:
                prize_str = f"${prize:,.2f}"
                claim_amount = prize
            elif prize is None:
                prize_str = "Jackpot — pari-mutuel; check official winners"
                claim_amount = 1_000_000  # trigger HQ instructions
            else:
                prize_str = "See note (free ticket / non-cash)"
                claim_amount = 0

            st.success(f"### 🎉 You won — {result['tier']}\n\n"
                       f"**Estimated prize:** {prize_str}")

            st.markdown("#### How to claim")
            if claim_amount == 0 or (isinstance(prize, (int, float))
                                     and prize > 0 and prize <= 599):
                st.markdown(
                    "- **Any Texas Lottery retailer can pay you** — bring "
                    "the physical ticket in and hand it to the clerk.\n"
                    "- No forms or ID required for prizes under $600.\n"
                    "- Some retailers may pay up to $2,500 at their "
                    "discretion, but they aren't required to."
                )
            elif isinstance(prize, (int, float)) and prize < 5_000_000:
                st.markdown(
                    "- **Prizes of $600 or more** must be claimed at a "
                    "Texas Lottery Claim Center or by mail.\n"
                    "- Bring the signed ticket, a completed Claim Form, and "
                    "government-issued photo ID.\n"
                    "- Texas Lottery Claim Centers are in Austin, Dallas, "
                    "Fort Worth, Houston, San Antonio, and a few other "
                    "cities. Find the nearest at texaslottery.com or call "
                    "1-800-375-6886."
                )
            else:
                st.markdown(
                    "- **Jackpot / multi-million-dollar prize** — must be "
                    "claimed in person at Texas Lottery Commission "
                    "headquarters in Austin.\n"
                    "- Bring the signed ticket, completed Claim Form, and "
                    "photo ID.\n"
                    "- Consult a financial advisor and an attorney "
                    "*before* claiming — you have 180 days to decide "
                    "annuity vs. cash-value lump sum.\n"
                    "- Call the Texas Lottery at 1-800-375-6886 to book a "
                    "claim appointment."
                )

            st.markdown("#### Right now")
            st.markdown(
                "- **Sign the back of the ticket immediately** — an "
                "unsigned winning ticket is bearer paper.\n"
                "- **Photograph the front and back** of the ticket.\n"
                "- **Deadline:** you have **180 days from the draw date** "
                f"({chosen_draw['date']}) to claim. After that, the "
                "prize is forfeit.\n"
                "- Store the physical ticket somewhere secure until claim."
            )
        else:
            st.info(f"### Not a winner\n\n**{result['tier']}** "
                    "for this draw. Nothing to claim.")
            st.markdown("#### What now")
            st.markdown(
                "- **Nothing to do** — the ticket isn't a winner in any "
                "tier for this draw. You can safely discard or recycle it "
                "(no need to return it or take any action).\n"
                "- **Perspective on odds:** any single ticket is one of "
                "millions of possible combinations; over a lifetime of "
                "regular play the *expected* outcome is losses that "
                "exceed wins.  Treat any purchase as entertainment "
                "spending, not investment.\n"
                "- If lottery play has become uncomfortable, the Texas "
                "Council on Problem Gambling operates a 24/7 hotline: "
                "**1-800-522-4700**."
            )

        if result.get("note"):
            st.caption(result["note"])
        st.caption(
            "Prize amounts here are the Texas Lottery's published $1-play "
            "base payouts. Actual payout may differ if you played with "
            "Extra! / Power Play / Megaplier multipliers, Combo, "
            "Sum It Up!, or Fireball add-ons — those aren't modelled. For "
            "the official winners page and exact pari-mutuel amounts, "
            "visit texaslottery.com."
        )

    if submitted and input_ok:
        result = check_ticket(
            check_game,
            user_main=user_main,
            draw_main=chosen["main"],
            user_bonus=user_bonus,
            draw_bonus=chosen["bonus"],
            play_type=play_type,
            dollar_play=dollar_play,
        )
        _result_dialog(result, check_g, chosen, user_main, user_bonus)

# ==================================================================
# Audit — is this game statistically random?
# ==================================================================

with tab_audit:
    st.subheader("Is this game's history statistically random?")
    st.write(
        "The audit runs multiple tests against the game's history. Each "
        "test targets a different way a lottery could be *un*fair "
        "(unequal frequencies, streaks, ball pairs, drift, etc.). The "
        "**family-wise verdict** below combines all of them and applies "
        "Holm correction — the honest bottom line after accounting for "
        "the number of tests run."
    )

    audit_game = st.selectbox(
        "Choose a game", list(GAMES.keys()), key="audit_game")
    game = GAMES[audit_game]
    _, era_draws = get_draws(audit_game)

    # -----------------------------------------------------------------
    # Compute all audit p-values (cache-hit after first run)
    # -----------------------------------------------------------------
    with st.spinner("Running full audit (cached after first run)..."):
        chi = chi_square_ball_frequency(era_draws, game)
        family: list = [("Frequency (χ² MC)", chi["p"])]

        if game.game_type == "kn":
            obs_lb = ljung_box_per_ball(era_draws, game, lags=10)
            obs_runs = runs_test_draw_sums(era_draws, game)
            s_null = mc_serial_dependence_null(game, D=len(era_draws),
                                               n_sim=100, seed=42, lags=10)
            p_max_lb = float(np.mean(s_null["max_ljung_box"] >= obs_lb["max_stat"]))
            p_prop_lb = float(np.mean(s_null["prop_lb_below_05"] >= obs_lb["prop_below_05"]))
            family += [
                ("Serial: max Ljung–Box", p_max_lb),
                ("Serial: prop LB<0.05", p_prop_lb),
                ("Serial: runs on sums", obs_runs["p"]),
            ]

            obs_g = gap_test_aggregate(era_draws, game)
            g_null = mc_gap_test_null(game, D=len(era_draws),
                                      n_sim=100, seed=42)
            p_g_max = float(np.mean(g_null["max_chi2"] >= obs_g["max_stat"]))
            p_g_prop = float(np.mean(
                g_null["prop_below_05"] >= obs_g["prop_below_05"]))
            family += [
                ("Gap: worst-ball χ²", p_g_max),
                ("Gap: prop below 0.05", p_g_prop),
            ]

            obs_p = pair_cooccurrence_aggregate(era_draws, game)
            p_null = mc_pair_cooccurrence_null(game, D=len(era_draws),
                                                n_sim=200, seed=42)
            p_pair_max = float(np.mean(p_null["max_z"] >= obs_p["max_z"]))
            p_pair_chi = float(np.mean(p_null["chi2_like"] >= obs_p["chi2_like"]))
            family += [
                ("Pair: max |z|", p_pair_max),
                ("Pair: χ²-like", p_pair_chi),
            ]

            obs_c = cusum_drift_aggregate(era_draws, game)
            c_null = mc_cusum_drift_null(game, D=len(era_draws),
                                         n_sim=200, seed=42)
            p_drift = float(np.mean(c_null["max_excursion"] >= obs_c["max_excursion"]))
            family += [("Drift: max CUSUM", p_drift)]

            if game.bonus_n:
                bchi = chi_square_bonus_ball(load_bonus_ball(game), game)
                family += [(f"Bonus ({game.bonus_label}) χ²", bchi["p"])]

            # Per-position marginals (assumes CSV preserves draw order —
            # verified empirically for all games at Phase 3 setup).
            pp_kn = chi_square_per_position_kn(era_draws, game)
            for r in pp_kn["per_position"]:
                family.append((f"Position {r['position']} χ²", r["p"]))
        else:
            # Digit games — chi + serial + per-position
            obs_lb = ljung_box_per_ball(era_draws, game, lags=10)
            obs_runs = runs_test_draw_sums(era_draws, game)
            s_null = mc_serial_dependence_null(game, D=len(era_draws),
                                               n_sim=100, seed=42, lags=10)
            p_max_lb = float(np.mean(s_null["max_ljung_box"] >= obs_lb["max_stat"]))
            p_prop_lb = float(np.mean(s_null["prop_lb_below_05"] >= obs_lb["prop_below_05"]))
            family += [
                ("Serial: max Ljung–Box", p_max_lb),
                ("Serial: prop LB<0.05", p_prop_lb),
                ("Serial: runs on sums", obs_runs["p"]),
            ]
            pp = chi_square_per_position_digit(era_draws, game)
            for r in pp["per_position"]:
                family.append((f"Position {r['position']} χ²", r["p"]))

    labels = [n for n, _ in family]
    raw_ps = [p for _, p in family]
    holm_ps = holm_correction(raw_ps)
    min_holm = min(holm_ps) if holm_ps else 1.0

    passes = min_holm >= 0.05
    verdict_icon = "✅" if passes else "⚠️"
    verdict_head = ("Passes the family-wise randomness audit" if passes
                    else "Family-wise audit flags a deviation")
    verdict_body = (
        f"Across **{len(raw_ps)} tests** (frequency, serial dependence, "
        f"gap, pair co-occurrence, drift, and where applicable bonus pool "
        f"or per-position digits), the smallest Holm-adjusted p-value is "
        f"**{min_holm:.3f}**. "
        + ("Every family-wise-corrected test is consistent with a fair "
           "random process." if passes else
           f"After correcting for the {len(raw_ps)} tests run, at least "
           f"one test still shows deviation worth investigating.")
    )
    box = st.success if passes else st.error
    box(f"### {verdict_icon} {verdict_head}\n\n{verdict_body}")

    with st.expander("Family-wise summary — every test, raw and Holm-adjusted"):
        st.caption(
            "Raw p is the MC-empirical (or analytic where valid) upper-tail "
            "probability. Holm-adjusted p controls family-wise error at "
            "any α ≥ max(adjusted). Adjusted p ≥ 0.05 → the family passes "
            "at α = 0.05."
        )
        df_family = pd.DataFrame({
            "Test": labels,
            "Raw p": [round(p, 4) for p in raw_ps],
            "Holm-adjusted p": [round(p, 4) for p in holm_ps],
            "Family-wise verdict": ["passes" if p >= 0.05 else "flag"
                                    for p in holm_ps],
        })
        st.dataframe(df_family, width="stretch", hide_index=True)

    st.markdown("#### How often each number has been drawn")
    st.caption(
        "Each bar is one number. The dashed line is the count you'd expect "
        "under a fair random process. Bars close to the line are normal; a "
        "sustained deviation across many bars would be evidence of a "
        "non-random process."
    )
    obs = chi["observed"]
    exp = float(chi["expected"][0])
    labels = list(range(1, game.n_main + 1)) if game.game_type == "kn" \
             else list(range(game.n_main))
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=obs, name="Observed"))
    fig.add_hline(y=exp, line_dash="dash",
                  annotation_text=f"Expected ≈ {exp:.0f}",
                  annotation_position="top left")
    fig.update_layout(xaxis_title="Number" if game.game_type == "kn" else "Digit",
                      yaxis_title="Times drawn", height=340,
                      margin=dict(l=10, r=10, t=10, b=10),
                      showlegend=False)
    st.plotly_chart(fig, width="stretch")

    # -----------------------------------------------------------------
    # Serial-dependence audit (B1) — tests the "independence" half of IID
    # -----------------------------------------------------------------
    st.divider()
    st.subheader("Serial-independence audit")
    st.caption(
        "The chi-square above tests only whether balls appear with equal "
        "*frequency*. This section tests the other half of \"random\": "
        "whether draws are independent of each other over time. A biased "
        "machine that produces streaks would pass the frequency test but "
        "fail here."
    )

    with st.spinner("Computing serial-dependence null (cached after first run)..."):
        obs_lb = ljung_box_per_ball(era_draws, game, lags=10)
        obs_runs = runs_test_draw_sums(era_draws, game)
        s_null = mc_serial_dependence_null(game, D=len(era_draws), n_sim=100,
                                           seed=42, lags=10)
    p_max_lb = float(np.mean(s_null["max_ljung_box"] >= obs_lb["max_stat"]))
    p_prop_lb = float(np.mean(s_null["prop_lb_below_05"] >= obs_lb["prop_below_05"]))

    sm1, sm2, sm3 = st.columns(3)
    sm1.metric(
        "Max Ljung-Box (any ball)",
        f"{obs_lb['max_stat']:.1f}",
        delta=f"MC p = {p_max_lb:.3f}",
        delta_color="off",
        help="Largest lag-10 autocorrelation statistic across all ball "
             "indicator series. MC-calibrated because per-ball series are "
             "not independent under H₀."
    )
    sm2.metric(
        "Balls flagged at α=0.05",
        f"{obs_lb['prop_below_05']*100:.1f}%",
        delta=f"MC p = {p_prop_lb:.3f}",
        delta_color="off",
        help=f"Under H₀ the MC-calibrated expectation is "
             f"~{s_null['prop_lb_below_05'].mean()*100:.1f}%."
    )
    sm3.metric(
        "Runs test on draw sums",
        f"p = {obs_runs['p']:.3f}",
        delta="passes" if obs_runs['p'] >= 0.05 else "flag",
        delta_color="off",
        help="Wald–Wolfowitz runs test on the sequence of draw sums vs. "
             "their median. Coarser than LB but a familiar single p-value."
    )

    verdict_pass = (p_max_lb >= 0.05 and p_prop_lb >= 0.05 and
                    obs_runs['p'] >= 0.05)
    if verdict_pass:
        st.success(
            "✅ **No serial dependence detected.** All three summaries land "
            "inside the MC-calibrated null band — the draws are consistent "
            "with independent draws over time."
        )
    else:
        st.warning(
            "⚠️ At least one serial-independence signal exceeds the "
            "MC-calibrated null. Investigate."
        )

    with st.expander("Serial-dependence details"):
        st.markdown(
            f"- **Ljung-Box (primary):** each of {obs_lb['n_series']} ball / "
            f"(position, digit) indicator series is tested for lag-10 "
            f"autocorrelation. We aggregate two ways:\n"
            f"  - **Max LB statistic** (single-worst ball): observed "
            f"{obs_lb['max_stat']:.2f}, MC null mean "
            f"{s_null['max_ljung_box'].mean():.2f}, "
            f"95th percentile {np.percentile(s_null['max_ljung_box'], 95):.2f}, "
            f"empirical p = {p_max_lb:.4f}.\n"
            f"  - **Proportion flagged at α=0.05:** observed "
            f"{obs_lb['prop_below_05']*100:.1f}%, MC null mean "
            f"{s_null['prop_lb_below_05'].mean()*100:.1f}% "
            f"(≈ 5% under strict independence, drifts up slightly from "
            f"within-draw negative correlation — the MC captures that).\n"
            f"- **Runs test (secondary):** collapses each K-ball draw to a "
            f"single sum and applies the Wald–Wolfowitz runs test vs. the "
            f"median. Coarse — it throws away most of the structure LB catches — "
            f"but included as a familiar sanity check. Observed p = "
            f"{obs_runs['p']:.4f} (null mean ≈ 0.5 under H₀; MC mean "
            f"{s_null['runs_test_p'].mean():.3f})."
        )

    # -----------------------------------------------------------------
    # Gap-test audit (B3) — kn games only. Per-ball gap distribution
    # against Geometric(K/N).
    # -----------------------------------------------------------------
    if game.game_type == "kn":
        st.divider()
        st.subheader("Gap-test audit")
        st.caption(
            "For each ball, the gap (number of draws) between consecutive "
            "appearances should follow Geometric(K/N) under H₀. Catches "
            "clumping — a ball that goes cold then hot — even when its "
            "total count looks normal."
        )
        with st.spinner("Computing gap-test null (cached after first run)..."):
            obs_g = gap_test_aggregate(era_draws, game)
            g_null = mc_gap_test_null(game, D=len(era_draws),
                                       n_sim=100, seed=42)
        p_g_max = float(np.mean(g_null["max_chi2"] >= obs_g["max_stat"]))
        p_g_prop = float(np.mean(
            g_null["prop_below_05"] >= obs_g["prop_below_05"]))

        gm1, gm2 = st.columns(2)
        gm1.metric(
            "Worst-fitting ball (χ²)",
            f"{obs_g['max_stat']:.1f}",
            delta=f"MC p = {p_g_max:.3f}",
            delta_color="off",
            help="Largest gap-test χ² across all balls."
        )
        gm2.metric(
            "Balls flagged at α=0.05",
            f"{obs_g['prop_below_05']*100:.1f}%",
            delta=f"MC p = {p_g_prop:.3f}",
            delta_color="off",
            help=f"Under H₀, MC-calibrated expectation "
                 f"~{g_null['prop_below_05'].mean()*100:.1f}%."
        )
        gap_pass = (p_g_max >= 0.05 and p_g_prop >= 0.05)
        if gap_pass:
            st.success("✅ **Gap distribution consistent with H₀** — no "
                       "detectable clumping in any single ball.")
        else:
            st.warning("⚠️ Gap distribution shows unusual clumping for at "
                       "least one ball.")

    # -----------------------------------------------------------------
    # Pairwise co-occurrence audit (B2) — kn games only.
    # -----------------------------------------------------------------
    if game.game_type == "kn":
        st.divider()
        st.subheader("Pairwise co-occurrence audit")
        st.caption(
            "Some physical defects (a warped ball, a sticky slot) surface as "
            "specific ball pairs being drawn together more often than "
            "chance — invisible to marginal frequency tests. This section "
            "flags the top outlier pairs."
        )
        with st.spinner("Computing pair-co-occurrence null (cached)..."):
            obs_p = pair_cooccurrence_aggregate(era_draws, game)
            p_null = mc_pair_cooccurrence_null(game, D=len(era_draws),
                                                n_sim=200, seed=42)
        p_pair_max = float(np.mean(p_null["max_z"] >= obs_p["max_z"]))
        p_pair_chi = float(np.mean(p_null["chi2_like"] >= obs_p["chi2_like"]))

        pm1, pm2 = st.columns(2)
        pm1.metric(
            "Max |z| across all pairs",
            f"{obs_p['max_z']:.2f}",
            delta=f"MC p = {p_pair_max:.3f}",
            delta_color="off",
            help=f"Largest standardized deviation from expected across "
                 f"{obs_p['n_pairs']:,} pairs. Under H₀ MC null 95th "
                 f"percentile ≈ {np.percentile(p_null['max_z'], 95):.2f}."
        )
        pm2.metric(
            "χ²-like pair aggregate",
            f"{obs_p['chi2_like']:.0f}",
            delta=f"MC p = {p_pair_chi:.3f}",
            delta_color="off",
        )
        pair_pass = (p_pair_max >= 0.05 and p_pair_chi >= 0.05)
        if pair_pass:
            st.success(
                "✅ **No pairwise anomalies detected.** All observed pair "
                "counts sit inside the MC-calibrated null band."
            )
        else:
            st.warning(
                "⚠️ Unusual pair-level structure — investigate the top "
                "outliers below."
            )

        with st.expander("Top 5 outlier pairs"):
            st.caption(
                f"Expected co-occurrence per pair under H₀: "
                f"{obs_p['expected_per_pair']:.2f}. z-scores use "
                f"Binomial(D, K(K−1)/[N(N−1)]) variance. Note: an isolated "
                f"large |z| doesn't itself matter — the MC-calibrated "
                f"aggregate above corrects for multiple testing."
            )
            df_pairs = pd.DataFrame(obs_p["top_pairs"])
            st.dataframe(df_pairs, width="stretch", hide_index=True)

    # -----------------------------------------------------------------
    # Within-era drift (B4) — CUSUM + optional rolling-window visual
    # -----------------------------------------------------------------
    if game.game_type == "kn":
        st.divider()
        st.subheader("Within-era drift audit")
        st.caption(
            "The pooled chi-square averages away slow physical change — a "
            "ball whose draw rate slides across years but averages out. "
            "CUSUM tracks the cumulative deviation of each ball's rate; a "
            "large max excursion indicates drift."
        )
        with st.spinner("Computing drift null (cached)..."):
            obs_c = cusum_drift_aggregate(era_draws, game)
            c_null = mc_cusum_drift_null(game, D=len(era_draws),
                                         n_sim=200, seed=42)
        p_drift = float(np.mean(c_null["max_excursion"] >= obs_c["max_excursion"]))

        cm1, cm2 = st.columns(2)
        cm1.metric(
            "Max cumulative excursion",
            f"{obs_c['max_excursion']:.1f}",
            delta=f"MC p = {p_drift:.3f}",
            delta_color="off",
            help=f"MC null 95th percentile ≈ "
                 f"{np.percentile(c_null['max_excursion'], 95):.1f}."
        )
        cm2.metric(
            "Worst ball",
            f"#{obs_c['worst_ball']}",
            help="Ball with the largest cumulative deviation over time."
        )
        drift_pass = p_drift >= 0.05
        if drift_pass:
            st.success("✅ **No detectable drift.** Cumulative deviations "
                       "for every ball stay within the MC-calibrated null band.")
        else:
            st.warning(f"⚠️ Ball #{obs_c['worst_ball']} shows drift larger "
                       f"than 95% of simulated fair histories.")

        with st.expander("Rolling-window frequency (visual)"):
            window = max(50, len(era_draws) // 20)
            st.caption(
                f"Frequency of the S1 top-3 balls over rolling windows of "
                f"{window} draws. The dashed line is the H₀-expected count "
                f"per window."
            )
            # Show top-3 most-frequent balls from S1
            s1 = s1_most_frequent(era_draws, game)
            expected_per_window = window * game.k_main / game.n_main
            dr_fig = go.Figure()
            for b in s1[:3]:
                y = rolling_frequency(era_draws, game, ball=b, window=window)
                if len(y):
                    dates = [era_draws[t + window - 1][0] for t in range(len(y))]
                    dr_fig.add_trace(go.Scatter(x=dates, y=y,
                                                mode="lines",
                                                name=f"Ball {b}"))
            dr_fig.add_hline(y=expected_per_window, line_dash="dash",
                             annotation_text=f"Expected ≈ {expected_per_window:.1f}",
                             annotation_position="top left")
            dr_fig.update_layout(xaxis_title="Draw date",
                                 yaxis_title=f"Appearances in last {window} draws",
                                 height=300,
                                 margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(dr_fig, width="stretch")

    # -----------------------------------------------------------------
    # Draw-order per-position marginals (B5) — kn games only.
    # -----------------------------------------------------------------
    if game.game_type == "kn":
        with st.expander("Per-position marginals (draw-order test)"):
            st.caption(
                "The CSV columns preserve draw order (verified empirically — "
                "each position's marginal ball mean sits at (N+1)/2). Under "
                "H₀ each of the K positions is marginally uniform on 1..N. "
                "Reject → an ordering-specific defect (e.g., a ball being "
                "consistently drawn first)."
            )
            pp_kn_full = chi_square_per_position_kn(era_draws, game)
            rows = [{"Position": r["position"], "χ²": round(r["chi2"], 2),
                     "df": r["df"], "p": round(r["p"], 4),
                     "Verdict": "passes" if r["p"] >= 0.05 else "flag"}
                    for r in pp_kn_full["per_position"]]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            st.caption(
                "Individual per-position p-values here are uncorrected. "
                "They roll into the family-wise Holm correction at the top "
                "of this tab, where any single flag is decisively "
                "neutralized by the multiple-testing adjustment."
            )

    # Bonus-pool audit (Powerball / Mega Ball / Bonus Ball) — K=1 → textbook exact
    if game.bonus_n:
        st.markdown(f"#### {game.bonus_label} — separate pool audit (K=1)")
        st.caption(
            f"The {game.bonus_label} is drawn from a separate machine of "
            f"1..{game.bonus_n}. K=1 means no within-draw correlation, so "
            f"the textbook χ²(df=N−1) is exact — no MC correction needed."
        )
        bonus_vals = load_bonus_ball(game)
        bchi = chi_square_bonus_ball(bonus_vals, game)
        bm1, bm2, bm3 = st.columns(3)
        bm1.metric("Bonus draws", f"{bchi['D']:,}")
        bm2.metric("χ² statistic", f"{bchi['chi2']:.1f}",
                   help=f"df = {bchi['df']}")
        bm3.metric("p-value", f"{bchi['p']:.4f}",
                   delta="passes" if bchi['p'] >= 0.05 else "REJECT H₀",
                   delta_color="off")
        blabels = list(range(1, game.bonus_n + 1))
        bfig = go.Figure()
        bfig.add_trace(go.Bar(x=blabels, y=bchi["observed"]))
        bfig.add_hline(y=float(bchi["expected"][0]), line_dash="dash",
                       annotation_text=f"Expected ≈ {bchi['expected'][0]:.1f}",
                       annotation_position="top left")
        bfig.update_layout(xaxis_title=game.bonus_label,
                           yaxis_title="Times drawn",
                           height=260, margin=dict(l=10, r=10, t=10, b=10),
                           showlegend=False)
        st.plotly_chart(bfig, width="stretch")

    with st.expander("Statistical details"):
        st.markdown(
            f"- **Test:** chi-square goodness-of-fit against a uniform "
            f"distribution\n"
            f"- **χ² statistic:** {chi['chi2']:.2f}\n"
            f"- **p-value (reported):** {chi['p']:.4f}"
        )
        if game.game_type == "kn":
            null_mean = chi.get("null_mean")
            expected_mean = chi.get("null_expected_mean")
            n_sim = chi.get("n_sim")
            st.markdown(
                f"- **Method:** Monte Carlo empirical p from **{n_sim:,}** "
                f"simulated fair K-of-N histories at the same D, K, N. "
                f"Textbook χ²(df=N−1) is *miscalibrated* for k-of-N draws "
                f"(within-draw balls are negatively correlated → statistic "
                f"has mean **N−K = {expected_mean:.0f}**, not N−1 = "
                f"{chi['df']}).\n"
                f"- **MC null mean:** {null_mean:.2f} "
                f"(should ≈ {expected_mean:.0f} — validated).\n"
                f"- **Analytic χ²(df=N−1) p-value** (deprecated, "
                f"conservative): {chi['p_analytic']:.4f}"
            )
        else:
            st.markdown(
                f"- **Degrees of freedom:** {chi['df']}\n"
                f"- **Method:** analytic χ²(df=N−1). Digit positions are "
                f"genuinely independent under H₀, so no MC correction is "
                f"needed."
            )
        st.caption(
            "p ≥ 0.05: consistent with a fair random process. "
            "p < 0.05: worth investigating (but see family-wise correction "
            "in Methods — with ~6 game-level tests the α = 0.05 threshold "
            "produces false positives at the ~30% family-wise error rate)."
        )
        if game.game_type == "digit":
            st.markdown("**Per-position test (digit games)**")
            st.caption(
                "Each digit position is tested separately. Under a fair "
                "process, all four p-values should be above 0.05."
            )
            pp = chi_square_per_position_digit(era_draws, game)
            rows = [{"Position": r["position"], "χ²": round(r["chi2"], 2),
                     "df": r["df"], "p": round(r["p"], 4),
                     "Result": "Passes" if r["p"] >= 0.05 else "Deviation"}
                    for r in pp["per_position"]]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# ==================================================================
# Experiment — do "hot" numbers actually beat random?
# ==================================================================

with tab_experiment:
    st.subheader("Do \"most frequent\" numbers actually beat random?")
    st.write(
        "This is the experiment at the heart of the thesis. For a chosen "
        "game, we lock in four candidate sequences today, then score each "
        "against the next 50 real draws. If picking historically hot numbers "
        "carried any predictive signal, that strategy should systematically "
        "match more real balls than a random pick. Under a fair lottery, it "
        "shouldn't — and reporting that null result *is* the finding."
    )

    exp_game = st.selectbox("Choose a game", list(GAMES.keys()), key="exp_game")
    game = GAMES[exp_game]
    _, era_draws = get_draws(exp_game)

    if not game.kn_experiment_ok:
        st.warning(
            f"**Experiment not applicable to {exp_game}.** "
            f"{exp_game} is an exact-match digit game — the chance of "
            f"matching all {game.k_main} digits in one draw is "
            f"1 in {game.n_main ** game.k_main:,}. Over 50 draws you'd expect "
            f"{50 / (game.n_main ** game.k_main):.3f} exact matches by "
            f"chance, well below any detectable signal. Use the **Audit** "
            f"tab to check the game's randomness."
        )
        st.stop()

    # Precompute per-game numbers ----------------------------------
    mean, sd, lo, hi = null_band_for_matches(game, 50)
    weeks = 50 / max(game.draws_per_week, 1)
    entries = experiment.list_entries(game=exp_game)
    seed_s2 = 42
    s1 = s1_most_frequent(era_draws, game)
    s4 = s4_least_frequent(era_draws, game)
    s2 = s2_prng(game, seed_s2)
    qrng_stream, qrng_source = get_qrng_stream()
    s3 = s3_qrng(qrng_stream, game)

    # Status strip -------------------------------------------------
    st.divider()
    st.markdown(f"### {exp_game} · at a glance")
    c1, c2, c3 = st.columns(3)
    c1.metric("Locked sequences", f"{len(entries)}",
              help="Number of candidate sequences committed to the log.")
    scored_max = max((experiment.score_entry(e, era_draws)["n_scored"]
                      for e in entries), default=0)
    c2.metric("Draws scored", f"{scored_max} / 50",
              help="How far through the 50-draw window we are.")
    c3.metric("50 draws ≈", f"{weeks:.1f} weeks",
              help=f"At {game.draws_per_week} draws/week for this game.")

    # ------------------------------------------------------------------
    # STEP 1 — Meet the candidates
    # ------------------------------------------------------------------
    st.divider()
    st.markdown("### Step 1 — Meet the four candidate sequences")
    st.caption(
        f"Each is a set of {game.k_main} numbers from 1–{game.n_main}. "
        "S1 is the hypothesis under test; S2 and S3 are the random baselines; "
        "S4 is a symmetric control."
    )

    def _fmt(seq):
        return ", ".join(str(x) for x in seq)

    strat_rows = [
        {
            "Strategy": "S1 — most-frequent",
            "Sequence": _fmt(s1),
            "How derived": f"The {game.k_main} numbers that appeared most "
                           f"often in the {len(era_draws):,}-draw history.",
            "Role": "The hypothesis under test — does frequency predict future draws?",
        },
        {
            "Strategy": "S2 — PRNG baseline",
            "Sequence": _fmt(s2),
            "How derived": f"Uniform random pick via NumPy PCG64 (seed {seed_s2}).",
            "Role": "Random baseline. Under H₀ everything should tie with this.",
        },
        {
            "Strategy": "S3 — QRNG baseline",
            "Sequence": _fmt(s3),
            "How derived": f"Quantum-sourced entropy (`{qrng_source}`).",
            "Role": "A second baseline from a physically different randomness source.",
        },
        {
            "Strategy": "S4 — least-frequent",
            "Sequence": _fmt(s4),
            "How derived": f"The {game.k_main} numbers that appeared least "
                           f"often historically.",
            "Role": "Symmetric control. If S1 wins, S4 should lose by the same margin.",
        },
    ]
    st.dataframe(pd.DataFrame(strat_rows), width="stretch", hide_index=True)

    # ------------------------------------------------------------------
    # Walk-forward backtest — honest out-of-sample test of the S1 strategy
    # ------------------------------------------------------------------
    st.markdown("**How has the S1 strategy done historically? (walk-forward)**")
    st.caption(
        "For each historical draw past a 50-draw burn-in, we recompute S1 "
        "using **only** the draws that occurred before that date, then score "
        "it against the newly seen draw. This restores ticket-draw "
        "independence, so the observed distribution below is directly "
        "comparable to the H₀ theoretical distribution. Any large "
        "deviation would be real evidence against H₀ — not data snooping."
    )
    wf = get_walk_forward(exp_game, burn_in=50)
    n_scored = wf["n_scored"]
    obs_counts, exp_counts = wf["obs_counts"], wf["exp_counts"]
    backtest_rows = []
    for m in range(game.k_main + 1):
        backtest_rows.append({
            "Matches": m,
            "Observed draws": obs_counts[m],
            "Expected under H₀": f"{exp_counts[m]:.1f}",
            "Observed %": f"{obs_counts[m] / n_scored * 100:.2f}%",
            "Expected %": f"{exp_counts[m] / n_scored * 100:.2f}%",
        })
    st.dataframe(pd.DataFrame(backtest_rows), width="stretch", hide_index=True)
    obs_3plus = sum(obs_counts[3:])
    exp_3plus = sum(exp_counts[3:])

    # Monte Carlo null for the walk-forward statistic. The analytic z-score
    # assumed independent m_t, but walk-forward tickets share past draws;
    # the true variance is captured by simulating fair histories and
    # running the exact same walk_forward_backtest on each.
    thorough = st.toggle(
        "Thorough MC null (n_sim = 2000, slower)", value=False,
        key=f"wf_thorough_{exp_game}",
        help="Off: n_sim = 200 (~seconds). On: n_sim = 2,000 (~minute). "
             "Cached to disk keyed on the CSV mtimes."
    )
    n_sim = 2000 if thorough else 200
    with st.spinner(f"Building MC null (n_sim = {n_sim})..."):
        null = mc_walk_forward_null(game, D=len(era_draws), burn_in=50,
                                    n_sim=n_sim, seed=42)
    pinfo = mc_walk_forward_pvalue(obs_3plus, null["counts_3plus"])

    metric_label = ("matched 3+ balls" if game.game_type == "kn"
                    else f"was an exact {game.k_main}-digit match")
    st.caption(
        f"Over {n_scored:,} scored draws (burn-in = 50), the prospectively-"
        f"chosen S1 {metric_label} in **{obs_3plus:,}** draws.  "
        f"**Analytic expected** (assumes independent draws, systematically "
        f"understates variance): {exp_3plus:.1f}.  "
        f"**MC empirical null**: mean = {pinfo['null_mean']:.2f}, "
        f"std = {pinfo['null_std']:.2f}, "
        f"5–95% range = [{pinfo['null_p05']:.0f}, {pinfo['null_p95']:.0f}]  "
        f"(n_sim = {pinfo['n_sim']}).  "
        f"**MC empirical p** (upper-tail: fraction of simulated fair "
        f"histories that hit ≥ {obs_3plus}) = {pinfo['empirical_p']:.4f}.  "
        f"p ≥ 0.05 is consistent with H₀."
    )
    st.divider()
    st.markdown("### Step 2 — Lock the sequences for the tracking window")
    if entries:
        st.success(
            f"You already have {len(entries)} locked entries for {exp_game}. "
            "Scroll to Step 3 to see how they're performing. "
            "You can lock additional sequences below if you want — each lock "
            "is immutable."
        )
    else:
        st.info(
            "Nothing locked yet. Locking writes the sequences to "
            "`experiment_log.json` as an append-only record — you cannot "
            "quietly re-pick after seeing the first draw. That is what makes "
            "the result statistically defensible."
        )

    with st.expander("Lock sequences now", expanded=(len(entries) == 0)):
        default_start = era_draws[-1][0]
        colA, colB = st.columns(2)
        with colA:
            window_start = st.date_input(
                "Window start date",
                value=default_start,
                help="Only draws on or after this date count toward the window.",
            )
        with colB:
            window_size = st.number_input(
                "Window size (draws)",
                value=50, min_value=1, max_value=500, step=1,
                help="50 is the pre-registered default; larger = more power.",
            )
        to_lock = st.multiselect(
            "Which strategies to lock?",
            ["S1", "S2", "S3", "S4"],
            default=["S1", "S2", "S3", "S4"],
        )
        if st.button("Lock now (immutable)", type="primary",
                     disabled=(not to_lock)):
            map_seq = {
                "S1": (s1, "S1_most_freq",
                       f"top-{game.k_main} on {len(era_draws)} draws"),
                "S2": (s2, "S2_prng", f"PCG64 seed={seed_s2}"),
                "S3": (s3, "S3_qrng", f"source={qrng_source}"),
                "S4": (s4, "S4_least_freq",
                       f"bottom-{game.k_main} on {len(era_draws)} draws"),
            }
            for lbl in to_lock:
                seq, strat, detail = map_seq[lbl]
                e = experiment.append_entry(
                    game=exp_game, strategy=strat, sequence=seq,
                    window_start_date=window_start,
                    window_size=int(window_size),
                    source_detail=detail,
                )
                st.success(f"Locked entry #{e['id']}: {strat}")
            st.rerun()

    # ------------------------------------------------------------------
    # STEP 3 — Tracking dashboard
    # ------------------------------------------------------------------
    st.divider()
    st.markdown("### Step 3 — Watch the tracking window fill up")
    if not entries:
        st.info("Lock sequences in Step 2 to see the tracker.")
    else:
        rows = []
        cum_series = {}
        for e in entries:
            sc = experiment.score_entry(e, era_draws)
            rows.append({
                "id": e["id"], "strategy": e["strategy"],
                "sequence": ", ".join(str(x) for x in e["sequence"]),
                "window start": e["window_start_date"],
                "scored / target": f"{sc['n_scored']} / {e['window_size']}",
                "matches": sc["total_matches"],
            })
            cum_series[f"#{e['id']} {e['strategy']}"] = sc

        st.markdown("**Where each strategy stands**")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        st.markdown("**Cumulative matches vs. the null-hypothesis band**")
        st.caption(
            "The gray band is the range you'd expect under a fair lottery "
            "(95% confidence). Any strategy that stays inside the band is "
            "behaving exactly as if it were picked randomly — no signal."
        )
        fig = go.Figure()
        max_n = 0
        for label, sc in cum_series.items():
            fig.add_trace(go.Scatter(
                x=list(range(1, len(sc["cumulative"]) + 1)),
                y=sc["cumulative"], mode="lines+markers", name=label,
            ))
            max_n = max(max_n, len(sc["cumulative"]))
        if max_n > 0:
            xs = list(range(1, max_n + 1))
            fig.add_trace(go.Scatter(
                x=xs, y=[mean * n for n in xs], mode="lines",
                line=dict(color="gray", dash="dash"), name="Expected under H₀",
            ))
            fig.add_trace(go.Scatter(
                x=xs, y=[mean * n + 1.96 * sd * np.sqrt(n) for n in xs],
                mode="lines", line=dict(color="lightgray"),
                name="95% upper",
            ))
            fig.add_trace(go.Scatter(
                x=xs, y=[mean * n - 1.96 * sd * np.sqrt(n) for n in xs],
                mode="lines", line=dict(color="lightgray"),
                fill="tonexty", name="95% lower",
            ))
        fig.update_layout(xaxis_title="Draws scored",
                          yaxis_title="Cumulative matches",
                          height=430,
                          margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")

        eligible = [(lbl, sc) for lbl, sc in cum_series.items()
                    if sc["n_scored"] >= 10]
        with st.expander("Statistical details — pairwise strategy comparisons"):
            if len(eligible) < 2:
                st.caption("Need at least 2 strategies with 10+ scored draws.")
            else:
                st.caption(
                    "Each row compares two strategies with a paired "
                    "permutation test on per-draw match counts. p ≥ 0.05 "
                    "means the two are statistically indistinguishable — "
                    "the expected finding under H₀."
                )
                min_n = min(sc["n_scored"] for _, sc in eligible)
                per_draw = {lbl: np.array(sc["per_draw"][:min_n])
                            for lbl, sc in eligible}
                labels = list(per_draw.keys())
                perm_rows = []
                for i in range(len(labels)):
                    for j in range(i + 1, len(labels)):
                        r = paired_permutation_test(per_draw[labels[i]],
                                                    per_draw[labels[j]])
                        perm_rows.append({
                            "A": labels[i], "B": labels[j],
                            "mean(A - B)": round(r["mean_diff"], 3),
                            "p (2-sided)": round(r["p"], 4),
                            "n": r["n"],
                        })
                df_p = pd.DataFrame(perm_rows)
                df_p["p (Bonferroni)"] = (df_p["p (2-sided)"] * len(df_p)) \
                                        .clip(upper=1.0)
                st.dataframe(df_p, width="stretch", hide_index=True)

    with st.expander("What N=50 can and cannot detect"):
        st.markdown(
            f"- **Expected matches per draw** under H₀: **{mean:.3f}** "
            f"({game.k_main}² / {game.n_main}).\n"
            f"- **50-draw 95% null band on the total:** [{lo:.1f}, {hi:.1f}]. "
            f"A strategy landing inside this band has *no detectable signal*.\n"
            f"- **Minimum detectable edge** at 80% power, α = 0.05: roughly "
            f"a {2.8 * sd / np.sqrt(50) / mean * 100:.0f}% "
            f"per-draw improvement over random. Anything smaller than that "
            f"will not be caught by N = 50 — you'd need many hundreds of "
            f"draws to detect subtle effects."
        )

# ==================================================================
# Methods
# ==================================================================

with tab_methods:
    st.subheader("Data")
    st.markdown(
        "All CSVs sourced from the Texas Lottery's own downloads and cached "
        "in `data/`. Re-download with `./download_data.sh`."
    )
    st.markdown(
        "**Era filter.** For each game, the era filter is set to the earliest "
        "date on which the *current* game format has been continuously in "
        "effect. Draws from earlier eras (e.g., when Mega Millions used a "
        "5-of-75 matrix, or when Cash Five used 5-of-37) are excluded because "
        "they come from a different sample space — mixing them would bias the "
        "frequency counts. This is why filter dates vary by game."
    )
    src_rows = []
    for name, g in GAMES.items():
        _, era = get_draws(name)
        src_rows.append({
            "Game": name, "Type": g.game_type,
            "K/N": f"{g.k_main}/{g.n_main}",
            "Draws in era": f"{len(era):,}",
            "Era start": g.era_start.isoformat(),
            "CSV files": len(g.csv_paths),
        })
    st.dataframe(pd.DataFrame(src_rows), width="stretch", hide_index=True)

    st.subheader("Tests")
    st.markdown(
        "- **χ² goodness-of-fit** on ball frequency (all games) and "
        "per-position digit frequency (digit games).\n"
        "- **Paired permutation test** for strategy-vs-strategy comparison "
        "in the Experiment tab (k-of-N games only).\n"
        "- **NIST SP 800-22 is not used** — it's a bitstream battery for "
        "cryptographic RNGs and does not apply to k-of-N or digit lottery "
        "draws. See `findings.md` §3."
    )

    st.subheader("PRNG and QRNG")
    qs, qsrc = get_qrng_stream()
    st.markdown(
        f"- **PRNG:** numpy `default_rng` (PCG64).\n"
        f"- **QRNG:** ANU legacy free endpoint (1024 bytes/req, 1 req/min). "
        f"Cached to `data/qrng_cache.json`. Current source: `{qsrc}`, "
        f"{len(qs)} bytes.\n"
        f"- **Fallback:** if ANU is unreachable, the app uses OS entropy "
        f"(`secrets.token_bytes`) and labels the source `os-fallback`."
    )

    st.subheader("This app does NOT claim")
    st.markdown(
        "- It does not predict future numbers.\n"
        "- It does not identify \"lucky\" or \"unlucky\" numbers with "
        "predictive value.\n"
        "- A null result at N=50 does not prove \"AI cannot predict "
        "lotteries\" — it means no effect above the detectable threshold "
        "(see `findings.md` §8.5)."
    )
