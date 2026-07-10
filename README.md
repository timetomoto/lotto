# Texas Lottery Randomness Auditor

A local thesis-artifact Streamlit app that audits the randomness quality of
Texas Lottery draw history and runs a **50-draw falsification experiment**
comparing candidate "most-winning" sequences against PRNG and QRNG baselines.

**This app is not a lottery predictor.** See `findings.md` §0 for the framing.

## Setup

```
python3 -m pip install -r requirements.txt
./download_data.sh      # optional; CSVs are already in data/
streamlit run app.py
```

Open http://localhost:8501.

## Data

`data/*.csv` are the Texas Lottery's own downloads:

- Lotto Texas — https://www.texaslottery.com/export/sites/lottery/Games/Lotto_Texas/Winning_Numbers/download.html
- Mega Millions — https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Winning_Numbers/download.html
- Powerball — https://www.texaslottery.com/export/sites/lottery/Games/Powerball/Winning_Numbers/download.html

The app filters each game to the current format era:

- Lotto Texas: from 2016-07-10 (6-of-54 stable)
- Mega Millions: from 2017-10-28 (5-of-70 era only)
- Powerball: from 2016-07-10 (5-of-69 stable)

## QRNG cache

The app pulls from the ANU legacy free endpoint on first run (1024 bytes,
one request under the 1-req/min limit) and caches to `data/qrng_cache.json`.
If the endpoint is unreachable, it falls back to OS entropy and labels the
source `os-fallback` in the UI. Grow the cache offline with:

```
python3 qrng.py 4096
```

## Experiment log

`experiment_log.json` is **append-only** — locking a candidate sequence in
Tab 3 writes an immutable entry. Check the file into git alongside the thesis.

## Files

```
app.py            Streamlit UI (5 tabs)
games.py          Current-era game configs (K, N, filter date)
loader.py         CSV loading and era filtering
strategies.py     S1 most-freq, S2 PRNG, S3 QRNG, S4 least-freq selection
stats_tests.py    χ², runs, gap, Ljung–Box, paired permutation
qrng.py           ANU legacy client with disk cache and OS fallback
experiment.py     Append-only experiment_log.json
findings.md       Research + math + go/no-go doc
```
