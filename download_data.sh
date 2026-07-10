#!/usr/bin/env bash
# Re-download every Texas Lottery non-scratch-off CSV into data/.
# Idempotent — overwrites existing files.
# Runs safely from any cwd (script uses its own directory).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p data
cd data

curl -fsSL -o lotto_texas.csv    "https://www.texaslottery.com/export/sites/lottery/Games/Lotto_Texas/Winning_Numbers/lottotexas.csv"
curl -fsSL -o mega_millions.csv  "https://www.texaslottery.com/export/sites/lottery/Games/Mega_Millions/Winning_Numbers/megamillions.csv"
curl -fsSL -o powerball.csv      "https://www.texaslottery.com/export/sites/lottery/Games/Powerball/Winning_Numbers/powerball.csv"
curl -fsSL -o cash_five.csv      "https://www.texaslottery.com/export/sites/lottery/Games/Cash_Five/Winning_Numbers/cashfive.csv"
curl -fsSL -o texas_two_step.csv "https://www.texaslottery.com/export/sites/lottery/Games/Texas_Two_Step/Winning_Numbers/texastwostep.csv"

for game_pair in "All_or_Nothing:allornothing:all_or_nothing" \
                 "Pick_3:pick3:pick_3" \
                 "Daily_4:daily4:daily_4"; do
  IFS=":" read -r remote_dir remote_slug local_prefix <<<"$game_pair"
  for slot in morning day evening night; do
    curl -fsSL -o "${local_prefix}_${slot}.csv" \
      "https://www.texaslottery.com/export/sites/lottery/Games/${remote_dir}/Winning_Numbers/${remote_slug}${slot}.csv"
  done
done

echo "$(date '+%Y-%m-%d %H:%M:%S') — downloaded 15 CSVs"
wc -l *.csv
