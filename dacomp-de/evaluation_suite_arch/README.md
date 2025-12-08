# DE-Arch Evaluation

Unified evaluator for DE-Arch tasks (English + Chinese). Gold comes from JSONL, prompt auto-switches by task id (`-zh` → Chinese).

## Modes supported
- Single task
- Single model directory (contains YAMLs named by task id)
- Experiment root containing multiple model directories (each with YAMLs)

## CLI
```bash
python evaluate.py \
  --project-path <model_dir_or_experiment_root> \
  [--task <id> | --tasks id1 id2 ... | --all] \
  [--model <evaluator_llm>] \
  [--gold-en-jsonl <path>] \
  [--gold-zh-jsonl <path>] \
  [--max-workers N] \
  [--list-models]
```

Defaults: evaluator LLM `o4-mini-2025-04-16`, gold JSONL from `config.py`, parallel workers 10.

## Examples

### Single model directory (all tasks)
```bash
python evaluate.py \
  --project-path /path/to/evaluation_output/dacomp_de_arch/exp1/modelA \
  --all \
  --model gemini-2.5-flash
```

### Single task
```bash
python evaluate.py \
  --project-path /path/to/.../modelA \
  --task dacomp-de-arch-001-zh \
  --model gemini-2.5-flash
```

### Experiment root (evaluate all models under it)
```bash
python evaluate.py \
  --project-path /path/to/evaluation_output/dacomp_de_arch/exp1 \
  --all \
  --model gemini-2.5-flash
```

## Notes
- Tasks are matched by YAML filename (e.g., `dacomp-de-arch-001`, `dacomp-de-arch-001-zh`) against the gold JSONL ids.
- Gold path uses config id; pred path uses provided id, so suffixes like `-zh` are supported.
- CS mode uses a temp DuckDB under each prediction dir (`tmp/cs_hybrid.duckdb`) and deletes it after evaluation.
