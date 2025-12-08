#!/usr/bin/env bash

# Runner for run_infer_de_arch.py (de-arch modeling_spec generation)
# Args (position-based):
#   1) MODEL            - required, e.g. openai_qwen3-235b-a22b
#   2) PARALLEL_WORKERS - optional, default 10
#   3) TASKS_SPEC       - optional, "all" or a specific task index (default: all)
#   4) EXP_NAME         - optional, default "default"
#   5) OVERWRITE_FLAG   - optional, non-empty to enable --overwrite
#   6) LANG_FILTER      - optional, one of all/zh/en (default all)
#   7) DATA_EN          - optional, override English data root
#   8) DATA_ZH          - optional, override Chinese data root
#   9) OUTPUT_BASE      - optional, override output base directory

set -eo pipefail

MODEL=$1
PARALLEL_WORKERS=${2:-10}
TASKS_SPEC=${3:-all}
EXP_NAME=${4:-default}
OVERWRITE_FLAG=$5
LANG_FILTER=${6:-all}
DATA_EN=$7
DATA_ZH=$8
OUTPUT_BASE=$9

if [ -z "$MODEL" ]; then
  echo "MODEL is required (matches --model of run_infer_de_arch.py)"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/ -> dacomp/ -> benchmarks/ -> evaluation/ -> Openhands-DE/
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PY_SCRIPT="$REPO_ROOT/evaluation/benchmarks/dacomp/run_infer_de_arch.py"

# Defaults used by the Python script if not overridden
[ -z "$DATA_EN" ] && DATA_EN="$REPO_ROOT/evaluation/benchmarks/dacomp/data/dacomp_de"
[ -z "$DATA_ZH" ] && DATA_ZH="$REPO_ROOT/evaluation/benchmarks/dacomp/data/dacomp_de_zh"
[ -z "$OUTPUT_BASE" ] && OUTPUT_BASE="$REPO_ROOT/evaluation_output/dacomp_de_arch"

LOG_DIR="$OUTPUT_BASE/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/de_arch_${MODEL}_${TIMESTAMP}.log"

CMD=(poetry run python "$PY_SCRIPT"
  --model "$MODEL"
  --parallel "$PARALLEL_WORKERS"
  --tasks "$TASKS_SPEC"
  --exp-name "$EXP_NAME"
  --lang-filter "$LANG_FILTER"
  --data-en "$DATA_EN"
  --data-zh "$DATA_ZH"
  --output-base "$OUTPUT_BASE"
)

if [ -n "$OVERWRITE_FLAG" ]; then
  CMD+=(--overwrite)
fi

echo "==================== DE-ARCH RUN ===================="
echo "MODEL: $MODEL"
echo "PARALLEL: $PARALLEL_WORKERS"
echo "TASKS: $TASKS_SPEC"
echo "EXP_NAME: $EXP_NAME"
echo "OVERWRITE: ${OVERWRITE_FLAG:-false}"
echo "LANG_FILTER: $LANG_FILTER"
echo "DATA_EN: $DATA_EN"
echo "DATA_ZH: $DATA_ZH"
echo "OUTPUT_BASE: $OUTPUT_BASE"
echo "LOG: $LOG_FILE"
echo "====================================================="

"${CMD[@]}" | tee "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "==================== COMPLETED ===================="
echo "Exit code: $EXIT_CODE"
echo "Log file: $LOG_FILE"
echo "==================================================="
exit $EXIT_CODE