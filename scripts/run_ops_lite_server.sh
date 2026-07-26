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

ensure_image() {
  local target=$1 source=$2
  docker image inspect "$target" >/dev/null 2>&1 || docker tag "$source" "$target"
}

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

ensure_image ghcr.io/hamsterstation/rcabench-baro:0a18961e fse-baro:0a18961e
ensure_image ghcr.io/hamsterstation/rcabench-art:ba8dfd3f fse-art:ba8dfd3f
ensure_image ghcr.io/hamsterstation/rcabench-eadro:4ee55dfc fse-eadro:4ee55dfc
ensure_image ghcr.io/hamsterstation/rcabench-causalrca:3f4ceee8 fse-causalrca:3f4ceee8

mark_stage normalize
"$CLI" normalize-ops-lite --config "$CONFIG" --snapshot "$SNAPSHOT" \
  > "$RUN_ROOT/logs/normalize.json"

run_and_evaluate baro

mark_stage prepare-art
ART_ASSETS=$("$CLI" prepare art --config "$CONFIG" --snapshot "$SNAPSHOT" \
  --cache-root "$RUN_ROOT/cache" --repository-root "$REPO")
run_and_evaluate art "$ART_ASSETS"

mark_stage prepare-eadro
EADRO_ASSETS=$("$CLI" prepare eadro --config "$CONFIG" --snapshot "$SNAPSHOT" \
  --cache-root "$RUN_ROOT/cache" --repository-root "$REPO")
run_and_evaluate eadro "$EADRO_ASSETS"

run_and_evaluate causalrca
mark_stage complete
