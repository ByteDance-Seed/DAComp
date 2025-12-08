#!/usr/bin/env bash

# Runner for DA tasks (run_infer_da.py)

set -eo pipefail
source "evaluation/utils/version_control.sh"

MODEL_CONFIG=$1
COMMIT_HASH=$2
AGENT=$3
NUM_TASKS=$4
NUM_WORKERS=$5
TASK_IDS=$6
SKIP_NUM=$7
DATA_TYPE=$8
PROMPT_LANGUAGE=$9
EXP_NAME=${10}
OVERWRITE_FLAG=${11}
LANGUAGE=${12}

[ -z "$NUM_WORKERS" ] && NUM_WORKERS=1 && echo "Number of workers not specified, use default $NUM_WORKERS"
[ -z "$AGENT" ] && AGENT="CodeActAgent" && echo "Agent not specified, use default $AGENT"
[ -z "$NUM_TASKS" ] && NUM_TASKS=1 && echo "Number of tasks not specified, use default $NUM_TASKS"
[ -z "$SKIP_NUM" ] && SKIP_NUM=0
[ -z "$DATA_TYPE" ] && DATA_TYPE="sqlite" && echo "Data type not specified, use default $DATA_TYPE"
[ -z "$PROMPT_LANGUAGE" ] && PROMPT_LANGUAGE="auto" && echo "Prompt language not specified, will auto-detect from task IDs"
[ -z "$EXP_NAME" ] && EXP_NAME="default"
[ -z "$LANGUAGE" ] && LANGUAGE="zh"

export DATAAGENT_PROMPT_LANG="$PROMPT_LANGUAGE"
export DATAAGENT_TASK_TYPE="da"
export DATAAGENT_LANG="$LANGUAGE"

# httpx/litellm choke on IPv6 CIDR entries in NO_PROXY (e.g. fd00::/8), so strip them.
if [ -n "$NO_PROXY" ]; then
  FILTERED_NO_PROXY=$(python3 <<'PY_NO_PROXY'
import os
entries = [h.strip() for h in os.environ.get("NO_PROXY", "").split(",") if h.strip()]
filtered = [h for h in entries if not (":" in h and "/" in h)]
print(",".join(filtered))
PY_NO_PROXY
)
  if [ "$FILTERED_NO_PROXY" != "$NO_PROXY" ]; then
    if [ -n "$FILTERED_NO_PROXY" ]; then
      echo "Sanitized NO_PROXY to remove IPv6 CIDR entries for httpx compatibility."
      export NO_PROXY="$FILTERED_NO_PROXY"
    else
      echo "Clearing NO_PROXY because only IPv6 CIDR entries were present."
      unset NO_PROXY
    fi
  fi
fi

checkout_eval_branch
get_openhands_version

echo "==================== DATAAGENT DA SETUP ===================="
echo "AGENT: $AGENT"
echo "OPENHANDS_VERSION: $OPENHANDS_VERSION"
echo "MODEL_CONFIG: $MODEL_CONFIG"
echo "NUM_TASKS: $NUM_TASKS"
echo "NUM_WORKERS: $NUM_WORKERS"
echo "SKIP_NUM: $SKIP_NUM"
echo "DATA_TYPE: $DATA_TYPE"
echo "PROMPT_LANGUAGE: $PROMPT_LANGUAGE (auto-detected per task if set to 'auto')"
echo "EXP_NAME: $EXP_NAME"
echo "OVERWRITE: ${OVERWRITE_FLAG:-false}"
echo "LANGUAGE (dataset): $LANGUAGE"
if [ -n "$TASK_IDS" ]; then
  echo "SPECIFIC_TASK_IDS: $TASK_IDS"
fi
echo "=================================================================="

mkdir -p logs

COMMAND="poetry run python evaluation/benchmarks/dacomp/run_infer_da.py \
  -c $AGENT \
  -l $MODEL_CONFIG \
  -i 100 \
  -n $NUM_TASKS \
  -j $NUM_WORKERS \
  --data-type $DATA_TYPE \
  --lang $LANGUAGE \
  --prompt-lang $PROMPT_LANGUAGE \
  --exp-name \"$EXP_NAME\""

if [ "$SKIP_NUM" -gt 0 ]; then
  echo "Skipping first $SKIP_NUM tasks"
  COMMAND="$COMMAND --skip-num $SKIP_NUM"
fi

if [ -n "$TASK_IDS" ]; then
  echo "Processing specific task IDs: $TASK_IDS"
  COMMAND="$COMMAND --task-ids ${TASK_IDS}"
fi

if [ -n "$OVERWRITE_FLAG" ]; then
  echo "Overwrite enabled"
  COMMAND="$COMMAND --overwrite"
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/dataagent_da_eval_${AGENT}_${DATA_TYPE}_${NUM_TASKS}tasks_${TIMESTAMP}.log"

echo "Starting dataagent DA evaluation at $(date)"
echo "Log will be saved to $LOG_FILE"

eval $COMMAND | tee $LOG_FILE
EXIT_CODE=${PIPESTATUS[0]}

echo ""
echo "==================== EVALUATION COMPLETED ===================="
echo "Completed at: $(date)"
echo "Exit code: $EXIT_CODE"
echo "Log file: $LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
  echo "Evaluation completed successfully!"
else
  echo "Evaluation failed with exit code $EXIT_CODE"
  echo "Check the log file for details: $LOG_FILE"
fi

echo "=================================================================="
exit $EXIT_CODE

