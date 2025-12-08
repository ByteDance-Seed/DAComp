# DAComp-DA Evaluation

## 0) If using our official baselines
From the corresponding agent folder in `methods/`, export run outputs into this evaluation suite before scoring:
```bash
python3 get_results.py openai_qwen3-coder-plus-test1 --output_dir ../dacomp-da/evaluation_suite/agent_results
python3 get_results.py gemini-2.5-pro-test1 --output_dir ../dacomp-da/evaluation_suite/agent_results
```

## 1) Agent results format
Place model outputs under `agent_results/<model_name>/`. Each instance needs:
- `<instance_id>.md` — final answer Markdown
- `<instance_id>-traj.txt` — trajectory/log text
- Any images referenced in the Markdown reside in the same instance folder.

Example: `agent_results/gpt-5-2025-08-07-test1/dacomp-006/{dacomp-006.md, dacomp-006-traj.txt, south_china_monthly_profit.png, ...}`

## 2) Configure models
Edit `evaluation_suite/core/config.py` and replace the placeholder endpoints/keys with your own. Env vars used by the example entries:
```bash
export AZURE_OPENAI_API_KEY=YOUR_KEY
export CUSTOM_MODEL_API_KEY=YOUR_KEY   # for custom OpenAI-compatible HTTP endpoints
export GEMINI_API_KEY=YOUR_KEY         # used by gemini-2.5-flash example
```

## 3) Run
The current run script expects all three model flags:
```bash
python3 llm_judge.py \
  --rubrics-model gemini-2.5-flash \
  --gsb-model-text gemini-2.5-flash \
  --gsb-model-vis gemini-2.5-flash \
  --inputs agent_results/gpt-5-2025-08-07-test1 \
  --max-workers 1

python3 llm_judge.py \
  --rubrics-model gemini-2.5-flash \
  --gsb-model-text gemini-2.5-flash \
  --gsb-model-vis gemini-2.5-flash \
  --inputs agent_results/openai_qwen3-coder-plus-test1-zh \
  --language zh \
  --max-workers 1
```
Notes:
- `--rubrics-model`: model config name used for rubric scoring.
- `--gsb-model-text`: model config for GSB text (readability/professionalism) scoring.
- `--gsb-model-vis`: model config for GSB visualization scoring.
- `--inputs` can be a folder under `agent_results` or a JSONL file; if omitted, all subfolders are used.
- `--metadata-root` points to per-instance rubrics/GSB references (default: `evaluation_suite/src_zh` or `src` when `--language en`).
- `--output-dir` controls where CSVs are written (default: `model_scores_zh` or `model_scores`).
- `--language` selects zh/en; it switches both rubrics (`src_zh` vs `src`) and output folders (`model_scores_zh` vs `model_scores`).

## 4) Aggregate scores
- English: `python3 get_score.py` reads `model_scores` and writes the six dimensions (completeness, accuracy, conclusiveness, readability, professionalism, visualization) to `model_scores/overall_results.csv`.
- Chinese: `python3 get_score_zh.py` reads `model_scores_zh` and writes the same six dimensions to `model_scores_zh/overall_results.csv`.
Notes for aggregation:
- `instance_id` filtering defaults to all tasks for the language (IDs present in the metadata directories). Override via CLI flags if needed; otherwise everything is included.
