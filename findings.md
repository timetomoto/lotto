# Texas Lottery Randomness Auditor — Research & Validation Findings

**Status:** Pre-code spike. Go/no-go recommendation at end.

---

## 0. Framing — falsification experiment (revised)

Original brief said "predict the lottery." **Revised scope (2026-07-10):** the app is not a predictor. It is a **falsification experiment** for the null hypothesis that lottery draws are IID uniform. Concretely: derive a candidate sequence from historical draw frequencies (a "most-winning" pick), track it against the next 20 real draws, update it adaptively as new draws land, and compare its hit rate against uniform-random baselines (PRNG, QRNG). Under H₀ the frequency-informed sequence and the random sequences have the *same* expected hit rate; if the frequency sequence systematically wins, that is evidence against H₀ — a newsworthy finding about lottery integrity, not proof of a prediction algorithm. Under H₀ the experiment is expected to return a null result, and reporting that null result **is** the thesis contribution.

This framing is academically defensible **provided the following are true in the thesis and the app UI:**

1. The thesis question is stated as "does a frequency-informed selection strategy outperform uniform-random selection over a fixed observation window?" — not "can we predict the lottery."
2. The expected outcome (null) is pre-registered before the 50-draw window begins.
3. The word "AI" is only used if an actual ML model is built. Picking the top-K most-frequent numbers is not AI. See §9 for language options.
4. The 50-draw window is acknowledged as **low statistical power** and the report includes an explicit power/effect-size discussion — see §8.5.
5. Any UI language suggesting the app "predicts" winners is removed. "Candidate sequence" and "tracking experiment" are honest terms.

Formal null hypothesis (unchanged):

> **H₀:** The draw sequence is a sample of IID draws from the discrete uniform distribution over the game's sample space (k-of-N without replacement per draw, draws independent across time).
> **H₁ (specific to the experiment):** A sequence selected from historical frequency data has a hit rate that differs from uniform-random selection over the observation window.

Failing to reject H₀ is the expected result and is a valid, publishable finding. Rejecting H₀ would be surprising and would require independent replication before drawing strong conclusions.

Formal null hypothesis for every test in the battery:

> **H₀:** The draw sequence is a sample of IID draws from the discrete uniform distribution over the game's sample space (k-of-N without replacement per draw, draws independent across time).
> **H₁:** The draw sequence deviates from H₀ in the direction the test is sensitive to (frequency imbalance, serial dependence, non-uniform gaps, etc.).

Failing to reject H₀ does **not** enable prediction — it confirms the draws look random, which is the *expected* result for a properly operated lottery. Rejecting H₀ would be a newsworthy finding about lottery integrity, not a prediction tool.

---

## 1. The three legitimate questions

| # | Question | Answer type |
|---|---|---|
| 1a | Do the published Texas Lottery draws pass standard randomness tests? | Per-game p-values across a test battery; reject/fail-to-reject H₀. |
| 1b | Are lottery draws statistically distinguishable from PRNG and QRNG output under the same tests, at matched sample sizes? | Three-way comparison (Lottery vs. PRNG vs. QRNG) of test statistics and p-value distributions. |
| 1c | **(New)** Over a 50-draw observation window, does a frequency-informed candidate sequence beat uniform-random selection in hit-rate against real Texas Lottery draws? | Head-to-head comparison of match counts across strategies; paired test; effect size + confidence interval. |

All three are answerable and academically defensible. None produces a "predicted next draw." Question 1c is the primary experiment the user requested; 1a and 1b are supporting analyses that give it context.

---

## 2. Data availability — Texas Lottery

The Texas Lottery publishes historical winning numbers per game under `texaslottery.com/export/sites/lottery/Games/<Game>/Winning_Numbers/`. CSV download endpoints are confirmed for the three national/flagship games; other Texas-specific games have past-numbers pages that follow the same URL pattern but the CSV endpoint was not individually verified in this spike and must be checked per game before build.

| Game | Draw structure | CSV confirmed | Coverage | URL |
|---|---|---|---|---|
| Mega Millions | 5 of 70 + Mega Ball 1 of 25 | ✅ | Dec 5, 2003 → present (TX participation) | https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Winning_Numbers/download.html |
| Powerball | 5 of 69 + Powerball 1 of 26 | ✅ | Feb 3, 2010 → present (TX participation) | https://www.texaslottery.com/export/sites/lottery/Games/Powerball/Winning_Numbers/download.html |
| Lotto Texas | 6 of 54 | ✅ (page confirms download.html endpoint) | 1992 → present per site year-selector | https://www.texaslottery.com/export/sites/lottery/Games/Lotto_Texas/Winning_Numbers/download.html |
| Texas Two Step | 4 of 35 + Bonus 1 of 35 | ⚠️ Unverified; page exists, same URL pattern likely | Not verified | https://www.texaslottery.com/export/sites/lottery/Games/Texas_Two_Step/Winning_Numbers/ |
| Cash Five | 5 of 35 | ⚠️ Unverified; page exists | Not verified | https://www.texaslottery.com/export/sites/lottery/Games/Cash_Five/Winning_Numbers/ |
| All or Nothing | 12 of 24 | ⚠️ Unverified; page exists | Not verified | https://www.texaslottery.com/export/sites/lottery/Games/All_or_Nothing/Winning_Numbers/ |
| Pick 3 | 3 digits, each 0–9 with replacement | ⚠️ Unverified | — | https://www.texaslottery.com/export/sites/lottery/Games/Pick_3/Winning_Numbers/ |
| Daily 4 | 4 digits, each 0–9 with replacement | ⚠️ Unverified | — | https://www.texaslottery.com/export/sites/lottery/Games/Daily_4/Winning_Numbers/ |

**License / terms:** No explicit machine-readable license was found on the CSV pages. The site carries the standard disclaimer *"In the case of a discrepancy between these numbers and the official drawing results, the official drawing results will prevail."* Winning numbers are public-record factual data (not copyrightable in the U.S. — facts are not protected by copyright). For a thesis, cite the source URL, retrieval date, and this disclaimer. Do **not** scrape aggressively; use the CSV endpoint directly. If distributing the data with the app, include the URL and disclaimer in the app footer.

**Note on `data.texas.gov`:** The Open Data Portal has a "Winners List of Texas Lottery Prizes" dataset — this is *prize winners*, not draw numbers. Not useful here.

**Recommendation:** Start MVP with **Lotto Texas** (single 6-of-54 draw, longest history, cleanest sample space for goodness-of-fit). Add Mega Millions and Powerball as secondary comparisons. Skip Pick 3 / Daily 4 (with-replacement per-digit; different test setup — nice stretch, not MVP).

---

## 3. Test battery

The draws are **k-of-N without replacement** per draw (or independent uniform digits for Pick 3 / Daily 4). NIST SP 800-22 is built for cryptographic bitstreams and doesn't apply — call that out explicitly in the thesis, don't try to shoehorn it in.

**Two design decisions that shaped the battery (post-implementation review, 2026-07-10):**

**Decision 1 — the textbook chi-square is *miscalibrated* for k-of-N.** For a fair K-of-N draw, each ball's count is Binomial(D, K/N), and within a draw the K balls are perfectly negatively correlated (they must be distinct). The Pearson χ² = Σ (O−E)²/E has expected value **N − K** under this null, not N − 1 as textbook χ²(df=N−1) assumes. The distortion scales with K/N: mild for Lotto Texas (48 vs 53) and severe for All or Nothing (12 vs 23 — the test is nearly uninformative under the textbook reference). **Fix implemented:** build the null empirically by simulating fair histories and computing the same statistic. Live in the app: MC null with n_sim = 10,000 per game, disk-cached; empirical mean verified to land at N − K for every game.

**Decision 2 — the walk-forward variance also needs empirical calibration.** The walk-forward backtest (S1_t derived from draws before t, scored against draws[t]) does not produce independent per-draw match counts: consecutive tickets share nearly their entire history, and each draw feeds into the next ticket. The analytic Var(cum_n) = n·σ² understates spread. **Fix implemented:** MC null that re-runs the actual `walk_forward_backtest` on simulated fair histories. Both production and MC call the same `s1_from_counter` / `s1_from_position_counters` helpers, so tie-breaking is identical by construction.

**Test battery per game (all MC-calibrated where the analytic reference is invalid):**

| Test | What it detects | Statistic | Calibration |
|---|---|---|---|
| **Frequency χ²** | Unequal marginal frequency across balls | Pearson χ² | MC empirical (analytic is biased for k-of-N) |
| **Serial: per-ball Ljung–Box** | Autocorrelation in per-ball indicator series | Max LB stat + proportion of balls with p<0.05 | MC empirical |
| **Serial: runs test on draw sums** | Coarse serial dependence | Wald–Wolfowitz | Analytic (approximately valid) |
| **Gap χ²** vs. Geometric(K/N) | Clumping in per-ball inter-arrival | Max χ² + proportion below 0.05 | MC empirical |
| **Pairwise co-occurrence** | Ball pairs riding together | Max \|z\| + χ²-like sum | MC empirical |
| **CUSUM drift** | Per-ball rate sliding over the era | Max cumulative excursion | MC empirical |
| **Bonus pool** (Powerball / Mega / Two Step) | Bonus ball non-uniformity | Pearson χ², K = 1 | Analytic (exact) |
| **Per-position marginals** | Ordering-specific bias | Pearson χ² per position | Analytic (exact per position; CSV order verified empirically) |
| **Per-position for digit games** | Position-specific bias in Pick 3 / Daily 4 | Pearson χ² per position | Analytic (exact) |

Family-wise: all p-values collected per game and Holm-adjusted. Verdict at α = 0.05 uses the *Holm-adjusted* minimum, not the raw minimum.

**Standalone helpers (documented, not currently wired in):**
- `paired_block_permutation_test` — for when we compare two walk-forward strategies (their per-draw differences are serially correlated; block permutation is the defensible test). Not currently used because the Experiment tab compares locked-vs-locked sequences whose D_i are genuinely independent.

Dieharder and the NIST STS binary are overkill and misaligned with the data shape — do not use them. All of the above runs in `scipy.stats` + `statsmodels` + `numpy`.

**Family-wise results across all 8 games (Phase 3 final):** every game passes Holm-adjusted at α = 0.05. The smallest Holm-adjusted p across all games and all tests is **0.077** (Powerball, position 3). Uncorrected raw p-values as low as 0.005 exist (Powerball position 3) but neutralize appropriately under the 15-test family-wise correction.

---

## 4. QRNG and PRNG sources

### QRNG: ANU Quantum Random Numbers

- **Legacy endpoint** (`https://qrng.anu.edu.au/API/jsonI.php`) is now hard rate-limited to **1 request per minute** — verified by direct probe on 2026-07-10. Exceeding the limit returns HTTP 500 with a rate-limit message pointing users to the new paid service.
- **Legacy request format:** `length` 1–1024 per request; data types `uint8`, `uint16`, `hex16`.
- **New endpoint** (`quantumnumbers.anu.edu.au`, AWS) requires an API key and is a paid service — explicitly out of scope per the "no paid APIs" constraint.
- **Recommendation:** treat 1024 bytes/request as the practical maximum per app boot. `qrng.py` in this repo pulls one request's worth of bytes on first run and caches to `data/qrng_cache.json`. A CLI helper (`python3 qrng.py <target_bytes>`) grows the cache offline by sleeping 65s between requests. Cache is honest about its source in the UI.
- **Fallback:** if ANU is unreachable or rate-limited, the app falls back to OS entropy (`secrets.token_bytes`) and labels the source `os-fallback`. Any thesis run that relies on the fallback must state so — it is hardware entropy (macOS Yarrow/Fortuna PRF, or Linux `getrandom`), not quantum-sourced.
- **Optional alternative:** NIST Beacon (`beacon.nist.gov`) publishes signed 512-bit hardware-entropy pulses every 60s. Not quantum, but public and always up. Not integrated in the MVP.

### PRNG baseline

- **`numpy.random.default_rng()`** which uses **PCG64**. Modern, well-tested, non-cryptographic but statistically strong general-purpose PRNG. This is the standard baseline for exactly this kind of experiment.
- Seed it deterministically and record the seed so results are reproducible for the thesis.
- Optional secondary PRNG for contrast: Mersenne Twister (`np.random.RandomState`, MT19937) — known to fail some stringent randomness tests, useful as a "here is what a failing source looks like" reference.

### Tradeoff summary

| Source | Pros | Cons |
|---|---|---|
| PCG64 (numpy default) | Fast, reproducible, statistically strong | Deterministic given seed — philosophically not "true" random |
| MT19937 (optional) | Historically important, known weaknesses | Old; not a good primary baseline |
| ANU QRNG legacy | Free, no auth, genuinely quantum | Being retired; small per-request length; ethics of hammering |
| ANU Quantum Numbers (new AWS) | Actively maintained | API key required, possibly paid tier |
| NIST Beacon | Free, signed, always up | Not quantum; slow (60s cadence) |

**Chosen stack for MVP:** PCG64 as PRNG baseline; ANU legacy QRNG pulled once into a cached local file as QRNG source; document a fallback to NIST Beacon in case ANU goes down mid-thesis.

---

## 5. Recommended minimal stack

This is a thesis artifact — one user (you) demoing it interactively, plus a screenshot pipeline for the paper. It is not a product. Optimize for **clarity of the analysis and reproducibility of results**, not deployability.

**Recommendation:** **Static frontend + Python analysis notebook, with results pre-computed to JSON.**

- **Analysis layer:** Python — `numpy`, `pandas`, `scipy.stats`, `statsmodels`, `matplotlib`. Run once, serialize test statistics and p-values to JSON.
- **Frontend:** A single-page site (Next.js static export, or plain Vite + React, or even a Jupyter notebook exported to HTML with `nbconvert`). Load the pre-computed JSON, render charts with **Plotly** or **Recharts**. If you want minimal ceremony, `streamlit` gives you charts + interactivity in ~50 lines and is very common for thesis demos.
- **Interactivity:** Let the user pick game, test, and RNG source; render the histogram/QQ/p-value view. That's the whole UI.
- **Why not a full FastAPI backend:** For a fixed dataset (draws don't change often; you'll pin a snapshot for the thesis anyway), a live backend is overhead. Pre-compute, ship JSON, done.

**Ranked stack options:**

1. **Streamlit** — fastest path, Python-only, native charts. Best default for a thesis demo. `streamlit run app.py`, deploy to Streamlit Community Cloud for free if you need a public link.
2. **Jupyter notebook exported via `nbconvert` to HTML + Voilà** — even simpler if interactivity is minimal.
3. **Next.js static + pre-computed JSON** — if you want a "real" web app for the portfolio; more work.

**MVP stack call: Streamlit.**

---

## 6. Proposed MVP feature list

1. **Data loader** — pulls Texas Lottery CSVs for Lotto Texas (primary), Mega Millions, Powerball; caches locally; shows last-updated date.
2. **Number-frequency dashboard** — per-game histogram of ball frequencies with expected line and χ² p-value.
3. **Randomness test battery panel** — runs test, gap test, Ljung–Box autocorrelation; per-test p-values with Bonferroni/BH correction toggle.
4. **RNG comparison** — same battery run against real lottery, PCG64 simulated draws, and cached ANU QRNG draws at matched sample sizes; side-by-side p-values.
5. **Candidate sequence generator** — the core experiment feature. User picks a game, picks a strategy (see §9), and the app produces a locked candidate sequence. Strategy, timestamp, and sequence are recorded to a persisted `experiment_log.json` so the sequence can't be quietly re-picked after the fact.
6. **50-draw tracking dashboard** — for each locked sequence, show cumulative hit count vs. expected (with 95% CI band) as new real draws arrive. One line per strategy on the same chart.
7. **Adaptive re-selection panel** — after each new draw, offer to update the candidate sequence using the new draw. Each update is logged as a new sub-experiment; the app never silently mutates a previously recorded sequence.
8. **Post-window analysis** — at draw 20, run a paired comparison of match counts across strategies (permutation test or paired t-test); report effect size, CI, and pre-registered conclusion.
9. **Methods, sources, and pre-registration page** — data sources with URLs and retrieval date, test definitions, PRNG seed, QRNG pull timestamp, and the pre-registered hypothesis and expected null outcome. Required for thesis reproducibility.

## What the app will NOT claim

- ❌ It will not "predict" future lottery numbers.
- ❌ It will not tell the user which numbers to actually buy.
- ❌ It will not label "hot" or "cold" numbers as *predictive* signals. Frequency displays are descriptive only; the app copy will state that under H₀ they carry no predictive information.
- ❌ It will not claim the QRNG is "more random" than the PRNG — the honest finding under H₀ is that all three sources should be *statistically indistinguishable* in these tests.
- ❌ It will not overstate a rejected H₀: a low p-value on one test out of many, without correction, is not evidence of lottery fraud.
- ❌ It will not conclude "AI cannot predict lotteries" from a 50-draw null result. The correct conclusion is "at N=50 and this effect-size sensitivity, no signal was detected." See §8.5 for the power discussion.

---

## 7. Open risks

| Risk | Mitigation |
|---|---|
| CSV endpoints for non-flagship TX games not verified — MVP may need to scrape HTML for those | Start with Lotto Texas / MM / PB (all confirmed); add others only if CSV confirmed. |
| No explicit license on the CSVs | Draw numbers are factual public records, not copyrightable; cite source URL + retrieval date + Texas Lottery disclaimer in the app. Do not redistribute as a "dataset product." |
| ANU legacy QRNG being retired mid-project | Pull QRNG data **once** into a cached local file; fall back to NIST Beacon if ANU goes offline. |
| Multiple-comparison false positives across a big test grid | Apply Bonferroni or Benjamini–Hochberg by default; make the correction visible in the UI. |
| Reader/reviewer confusion about "prediction" wording | Ruthless framing hygiene in title, copy, and thesis abstract: this is a **randomness audit and RNG comparison**, not a predictor. |
| Small sample sizes for some games | Report sample-size and power alongside p-values; do not compute tests that require more data than the game has. |
| Cherry-picking tests until one is significant | Pre-register the test battery in the thesis (list all tests, all games, all sources before running); publish all p-values, not just interesting ones. |
| 50-draw window has low statistical power — the experiment can only detect very large effects (~44–62% edge over random depending on game; see §8.5) | State this explicitly in the thesis. Report effect-size sensitivity, not just p-values. Do not conclude "AI can't predict" from a null result at N=50. |
| Adaptive re-selection could be gamed (consciously or unconsciously) to make a strategy look better after the fact | Log every sequence with a timestamp before the next draw occurs; make `experiment_log.json` append-only; check it into git. Pre-registered "frozen" sequences carry the primary result; adaptive versions are exploratory only. |
| "AI" language in the thesis when the strategy is just a frequency count | Match the language to the mechanism. Only claim "AI" if S6 (ML model) is actually built and trained with proper holdout. Otherwise say "frequency-informed selection." |
| Rare match-count outcomes over 50 draws will feel meaningful ("look, S1 beat S2 by 3!") but be within the null distribution | Always display results with the H₀ confidence band on the same chart, not just raw counts. Reader should be able to see whether the observed value is inside or outside the null band at a glance. |

---

## 8. 50-draw tracking experiment — design

### 8.1 Data reality check (10-year window, computed 2026-07-10)

Pulled directly from the Texas Lottery CSVs and filtered to the current game format:

| Game | Format | Filtered draws | Window start | K/N |
|---|---|---|---|---|
| Lotto Texas | 6-of-54 (stable through window) | **1,298** | 2016-07-13 | 6/54 |
| Mega Millions | 5-of-70 + MegaBall (change 2017-10-28) | **907** | 2017-10-31 | 5/70 |
| Powerball | 5-of-69 + Powerball (stable through window) | **1,298** | 2016-07-13 | 5/69 |

**Historical-frequency candidate sequences (S1 top-K, S4 bottom-K) — main balls only:**

| Game | S1 most-frequent | Count | S4 least-frequent | Count |
|---|---|---|---|---|
| Lotto Texas | {4, 8, 15, 31, 44, 52} | 166,165,165,162,160,159 | {40, 45, 46, 48, 50, 53} | 121,127,129,129,130,131 |
| Mega Millions | {3, 10, 17, 31, 42} | 84,81,80,77,76 | {23, 45, 51, 65, 67} | 49,52,52,52,54 |
| Powerball | {21, 28, 33, 36, 61} | 121,118,113,109,109 | {13, 26, 34, 46, 49} | 70,76,77,78,78 |

**Chi-square goodness-of-fit on the same 10-year data (H₀ = uniform):**

| Game | χ² | df | p | Verdict |
|---|---|---|---|---|
| Lotto Texas | 47.66 | 53 | 0.6815 | fail to reject H₀ |
| Mega Millions | 61.71 | 69 | 0.7213 | fail to reject H₀ |
| Powerball | 76.44 | 68 | 0.2259 | fail to reject H₀ |

Bottom line: the 10-year draws are statistically indistinguishable from uniform. The frequency spread that produces the S1/S4 lists above is fully explained by normal sampling noise. This is not a bug — it is Question 1a's answer, and it is the expected result. The S1 sequences are candidates *because the user asked for them*, not because there is any statistical evidence they will outperform random selection.

### 8.2 Selection strategies to compare

Every strategy must produce a sequence of the same shape as the target game. Run all four in parallel, one sequence per strategy per game per window.

| # | Strategy | What it does | Is it "AI"? |
|---|---|---|---|
| S1 | **Frequency-informed ("most-winning")** | Pick the K balls that appeared most often in the 10-year history. | No — a count. Do not call this AI. |
| S2 | **Uniform-random PRNG** | Draw K distinct balls from 1..N using PCG64. Reproducible via seed. | No — baseline. |
| S3 | **QRNG** | Draw K distinct balls from cached ANU QRNG bytes (legacy free endpoint). | No — baseline. |
| S4 | **Least-frequent ("cold")** | Pick the K balls that appeared *least* often. Under H₀ should perform identically to S1 and S2. Included so the gambler's-fallacy symmetry is visible. | No. |
| S5 (optional) | **Bayesian frequency updater** | Dirichlet-Multinomial posterior; pick top-K posterior means. | Borderline — a Bayesian model. |
| S6 (optional, only if the thesis makes an "AI" claim) | **Sequence model** (LSTM or small transformer) | Train on historical draws with proper holdout; pick top-K predicted probabilities. | Yes — this is ML. |

**MVP: S1 + S2 + S3 + S4.** Add S5 for a modeling story. Only add S6 if the thesis genuinely needs to claim "AI," and be honest that under H₀ it won't beat S2/S3 either.

### 8.3 Metric

- **Primary:** matches per draw = number of balls in the candidate sequence that also appear in the winning numbers (main-ball pool only for MVP; ignore MegaBall/Powerball).
- **Secondary:** hit-rate over the 50-draw window = total matches ÷ (50 × K).

### 8.4 Statistical test at end of window

For each pair of strategies (e.g., S1 vs. S2), a **paired permutation test** on the 50 per-draw match-count differences (paired because both strategies are scored on the same draws). Report:

- Observed mean difference (matches per draw)
- Two-sided p-value from the permutation distribution
- 95% bootstrap CI on the mean difference
- Bonferroni-adjusted p-value across all strategy pairs

**Do not** inspect intermediate windows and cherry-pick a stopping point — that is p-hacking. The 50th draw is the pre-registered stopping point.

### 8.5 Power analysis (computed on real data)

Per-draw match count for a fixed K-of-N ticket vs. a fresh K-of-N draw is Hypergeometric(N, K, K): μ = K²/N, σ² = K²(N−K)²/(N²(N−1)).

| Game | E[match]/draw | SD/draw | E[Σ] over 50 | SD[Σ] | 95% null band on Σ | Min detectable per-draw edge (α=.05, 80% power) |
|---|---|---|---|---|---|---|
| Lotto Texas | 0.667 | 0.733 | 33.33 | 5.18 | [23.2, 43.5] | Δ = 0.29 matches/draw = **~44% edge** |
| Mega Millions | 0.357 | 0.559 | 17.86 | 3.95 | [10.1, 25.6] | Δ = 0.22 = **~62% edge** |
| Powerball | 0.362 | 0.562 | 18.12 | 3.98 | [10.3, 25.9] | Δ = 0.22 = **~61% edge** |

**Real-time cost of the 50-draw window:**

| Game | Schedule | 50 draws ≈ |
|---|---|---|
| Lotto Texas | Mon/Wed/Sat | **~3.8 months** |
| Powerball | Mon/Wed/Sat | ~3.8 months |
| Mega Millions | Tue/Fri | ~5.8 months |

**Consequence:** better than N=20 (which needed ~70%+ edge) but still only detects **massive** effects. A null result over 50 draws is the expected outcome and does not disprove smaller edges. Do not conclude "AI can't predict lotteries" from a null at N=50; the correct conclusion is "at N=50 with sensitivity Δ, no effect was detected."

### 8.6 Adaptive re-selection

The user asked to update the sequence as we go. Statistically each update creates a new mini-experiment. Two options:

- **Option A — Frozen baseline + tracked adaptive:** at draw 0, lock one sequence per strategy and never touch it again. Also run a parallel adaptive version that re-derives after each new draw. Report both; the frozen baseline supports the pre-registered test, the adaptive version is exploratory.
- **Option B — Sliding window:** produce a new sequence at each draw, score only against the next one. 50 independent mini-experiments.

**Recommendation: Option A.** Preserves the pre-registered hypothesis while giving you the adaptive story.

### 8.7 Pre-registration checklist (must be done before draw 1 is scored)

1. Target game(s) fixed.
2. Strategies fixed.
3. Metric fixed.
4. Statistical test and correction fixed.
5. Sequences generated and logged with timestamps to `experiment_log.json`, checked into git.
6. Expected outcome (null) stated in the thesis draft.
7. Only then does draw 1 count.

If any of these change after draw 1, the pre-registration is broken and the window has to restart with a new one. Enforce this in the app — once the first draw is scored, the strategy list and metric definitions become read-only.

---

## 9. Go / No-Go

**Go — conditional on the falsification framing (§0) and pre-registration (§8.6).**

- ✅ All three legitimate questions (1a, 1b, 1c) are real, defensible, and cleanly answerable with public data and standard libraries.
- ✅ Data, tests, PRNG, and QRNG sources are all available today.
- ✅ Minimal stack (Streamlit + numpy/scipy/statsmodels) is well-matched to a thesis artifact.
- ✅ The 50-draw tracking experiment is a valid *falsification test* and is what the user actually wants to run.
- ⚠️ **Statistical-power condition:** the 50-draw window can only detect very large effects (~44–62% edge over random; see §8.5). The thesis must acknowledge this up front and frame the expected null result as an informative finding, not a "we tried, it didn't work."
- ⚠️ **Language condition:** the app UI and thesis must use "candidate sequence" and "tracking experiment" — not "predict." The word "AI" must match what is actually built (frequency count is not AI; a trained model is).
- ⚠️ **Pre-registration condition:** sequences, strategies, and the test must be locked in `experiment_log.json` and checked into git *before* draw 1 is scored. If this isn't enforced, the result is not defensible.
- ⛔ **Blocking condition (unchanged):** if the framing has to remain "predict the lottery" with no falsification / null-hypothesis language, this is a no-go — that claim would not survive academic review regardless of what the app produces.

Assuming the conditions are accepted: proceed to a scoping/implementation plan for the Streamlit MVP.

---

## Sources

- Texas Lottery — Mega Millions download page: https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Winning_Numbers/download.html
- Texas Lottery — Powerball download page: https://www.texaslottery.com/export/sites/lottery/Games/Powerball/Winning_Numbers/download.html
- Texas Lottery — Lotto Texas winning numbers: https://www.texaslottery.com/export/sites/lottery/Games/Lotto_Texas/Winning_Numbers/
- Texas Lottery — Games index: https://www.texaslottery.com/export/sites/lottery/Games/
- Texas Open Data Portal — Winners List (not draw numbers, for reference only): https://data.texas.gov/See-Category-Tile/Winners-List-of-Texas-Lottery-Prizes/54pj-3dxy
- ANU QRNG API documentation (legacy): https://qrng.anu.edu.au/contact/api-documentation/
- ANU Quantum Numbers (new AWS service): https://quantumnumbers.anu.edu.au
- NIST SP 800-22 documentation and software: https://csrc.nist.gov/projects/random-bit-generation/documentation-and-software
- NIST Randomness Beacon: https://beacon.nist.gov
- NIST Statistical Test Suite (reference implementation): https://github.com/terrillmoore/NIST-Statistical-Test-Suite
- Pearson goodness-of-fit background: https://real-statistics.com/chi-square-and-f-distributions/goodness-of-fit/
- Gap test description: https://metricgate.com/docs/gap-test/
- Randomness tests in lotteries (survey): https://grokipedia.com/page/Randomness_tests_in_lotteries
- Statistical analysis of lottery results (paper): https://www.wseas.us/e-library/conferences/2005lisbon/papers/496-181.pdf
- On IID and lottery predictability: https://lotterycodex.com/truly-random-lottery/
