#!/usr/bin/env bash

# export DATAAGENT_PROMPT_LANG=zh #agent的中英文

set -eo pipefail
source "evaluation/utils/version_control.sh"

MODEL_CONFIG=$1
COMMIT_HASH=$2
AGENT=$3
NUM_TASKS=$4
NUM_WORKERS=$5
TASK_IDS=$6
SKIP_NUM=$7
LANGUAGE=$8
PROMPT_LANGUAGE=$9
TASK_TYPE=${10}
EXP_NAME=${11}
OVERWRITE_FLAG=${12}

if [ -z "$NUM_WORKERS" ]; then
  NUM_WORKERS=1
  echo "Number of workers not specified, use default $NUM_WORKERS"
fi

if [ -z "$AGENT" ]; then
  echo "Agent not specified, use default CodeActAgent"
  AGENT="CodeActAgent"
fi

if [ -z "$NUM_TASKS" ]; then
  echo "Number of tasks not specified, use default 50"
  NUM_TASKS=50
fi

if [ -z "$SKIP_NUM" ]; then
  SKIP_NUM=0
fi

[ -z "$LANGUAGE" ] && LANGUAGE="zh"
[ -z "$PROMPT_LANGUAGE" ] && PROMPT_LANGUAGE="$LANGUAGE"
[ -z "$TASK_TYPE" ] && TASK_TYPE="all"
[ -z "$EXP_NAME" ] && EXP_NAME="default"

export DATAAGENT_LANG="$LANGUAGE"
export DATAAGENT_PROMPT_LANG="$PROMPT_LANGUAGE"
case "$TASK_TYPE" in
  impl)  export DATAAGENT_TASK_TYPE="de-impl" ;;
  evol)  export DATAAGENT_TASK_TYPE="de-evol" ;;
  *)     export DATAAGENT_TASK_TYPE="de" ;; 
esac

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

echo "==================== DATAAGENT DE EVALUATION SETUP ===================="
echo "AGENT: $AGENT"
echo "OPENHANDS_VERSION: $OPENHANDS_VERSION"
echo "MODEL_CONFIG: $MODEL_CONFIG"
echo "NUM_TASKS: $NUM_TASKS"
echo "NUM_WORKERS: $NUM_WORKERS"
echo "SKIP_NUM: $SKIP_NUM"
echo "LANGUAGE (dataset/source): $LANGUAGE"
echo "PROMPT_LANGUAGE (prompts/tools): $PROMPT_LANGUAGE"
echo "TASK_TYPE: $TASK_TYPE"
echo "EXP_NAME: $EXP_NAME"
echo "OVERWRITE: ${OVERWRITE_FLAG:-false}"
if [ -n "$TASK_IDS" ]; then
  echo "SPECIFIC_TASK_IDS: $TASK_IDS"
fi
echo "=================================================================="

mkdir -p logs

COMMAND="poetry run python evaluation/benchmarks/dacomp/run_infer_de.py \
  -c $AGENT \
  -l $MODEL_CONFIG \
  -i 200 \
  -n $NUM_TASKS \
  -j $NUM_WORKERS \
  --lang $LANGUAGE \
  --prompt-lang $PROMPT_LANGUAGE \
  --task-type $TASK_TYPE \
  --exp-name \"$EXP_NAME\""

if [ "$SKIP_NUM" -gt 0 ]; then
  echo "Skipping first $SKIP_NUM tasks"
  COMMAND="$COMMAND --skip-num $SKIP_NUM"
fi

if [ -n "$TASK_IDS" ]; then
  echo "Processing specific task IDs: $TASK_IDS"
  COMMAND="$COMMAND --task-ids $TASK_IDS"
fi

if [ -n "$OVERWRITE_FLAG" ]; then
  echo "Overwrite enabled"
  COMMAND="$COMMAND --overwrite"
fi

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="logs/dataagent_de_eval_${AGENT}_${NUM_TASKS}tasks_${TIMESTAMP}.log"

echo "Starting dataagent DE evaluation at $(date)"
echo "Log will be saved to $LOG_FILE"

eval $COMMAND | tee $LOG_FILE
EXIT_CODE=$?

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
