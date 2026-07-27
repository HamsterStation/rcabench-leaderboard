#!/usr/bin/env bash
set -Eeuo pipefail

REPO=${REPO:-/mnt/jfs-fixed/rcabench-leaderboard}
PYTHON_ENV=${PYTHON_ENV:-/mnt/jfs-fixed/rcabench-venv}
SNAPSHOT=${SNAPSHOT:-/mnt/jfs-fixed/ops-lite-9ac09981}
RUN_ROOT=${RUN_ROOT:-/mnt/jfs-fixed/ops-lite-runs/seed42}
CONFIG="$REPO/config/ops-lite.json"
CLI="$PYTHON_ENV/bin/rcabench-leaderboard"

mkdir -p "$RUN_ROOT/results" "$RUN_ROOT/metrics" "$RUN_ROOT/logs" "$RUN_ROOT/cache"
exec 9>"$RUN_ROOT/run.lock"
flock -n 9 || { echo "another OPS-Lite run is active" >&2; exit 2; }
echo $$ > "$RUN_ROOT/master.pid"

mark_stage() {
  printf '%s\n' "$1" > "$RUN_ROOT/stage.txt"
  date --iso-8601=seconds > "$RUN_ROOT/updated_at.txt"
}

trap 'mark_stage failed' ERR

run_and_evaluate() {
  local algorithm=$1 assets=${2:-}
  local asset_args=()
  [[ -n "$assets" ]] && asset_args=(--assets "$assets")
  mark_stage "run-$algorithm"
  "$CLI" run "$algorithm" --config "$CONFIG" --snapshot "$SNAPSHOT" \
    --output "$RUN_ROOT/results/$algorithm" \
    --container-runner "$REPO/containers/run_algorithm.py" "${asset_args[@]}"
  "$CLI" evaluate "$algorithm" --config "$CONFIG" --snapshot "$SNAPSHOT" \
    --results "$RUN_ROOT/results/$algorithm" \
    --output "$RUN_ROOT/metrics/$algorithm.json" --require-complete
}

mapfile -t ALGORITHMS < <("$PYTHON_ENV/bin/python" -c \
  'import sys; from rcabench_leaderboard.config import load_config; c=load_config(sys.argv[1]); print("\n".join(sorted(c["algorithms"])))' \
  "$CONFIG")
for algorithm in "${ALGORITHMS[@]}"; do
  image=$("$PYTHON_ENV/bin/python" -c \
    'import sys; from rcabench_leaderboard.config import load_config; print(load_config(sys.argv[1])["algorithms"][sys.argv[2]]["image"])' \
    "$CONFIG" "$algorithm")
  docker pull "$image"
done

mark_stage normalize
"$CLI" normalize-ops-lite --config "$CONFIG" --snapshot "$SNAPSHOT" \
  > "$RUN_ROOT/logs/normalize.json"

for algorithm in "${ALGORITHMS[@]}"; do
  preparation=$("$PYTHON_ENV/bin/python" -c \
    'import sys; from rcabench_leaderboard.config import load_config; print(load_config(sys.argv[1])["algorithms"][sys.argv[2]].get("preparation", ""))' \
    "$CONFIG" "$algorithm")
  assets=""
  if [[ -n "$preparation" ]]; then
    mark_stage "prepare-$algorithm"
    assets=$("$CLI" prepare "$algorithm" --config "$CONFIG" --snapshot "$SNAPSHOT" \
      --cache-root "$RUN_ROOT/cache" --repository-root "$REPO")
  fi
  run_and_evaluate "$algorithm" "$assets"
done
mark_stage complete
