# DE Agent Quickstart 🚀

This repository includes various runners for Data Engineering (DE) and Data Analysis (DA) tasks located in [evaluation/benchmarks/dacomp/scripts](evaluation/benchmarks/dacomp/scripts). These runners serve as wrappers for Python entry points within [evaluation/benchmarks/dacomp/](evaluation/benchmarks/dacomp/) and require a model configuration in the [config.toml](config.toml) file.

## 1. Configure Your Model in `config.toml` 📝

To set up your model, add an LLM entry (e.g., for Azure/OpenAI-style models):

```toml
[llm.gpt-5-2025-08-07-eval]
model = "gpt-5-2025-08-07"
api_key = ""
base_url = ""
temperature = 1.0
top_p = 1.0
max_output_tokens = 26384
timeout = 900
num_retries = 20
retry_min_wait = 1
retry_max_wait = 30
retry_multiplier = 1.0
extra_headers = { "X-TT-LOGID" = "" }
custom_llm_provider = "azure_raw"
api_version = "2024-03-01-preview"
```

Then reference this key (e.g., `llm.gpt-5-2025-08-07-eval`) using the `-l` / `--llm-config` flag in the scripts.

## 2. Data Layout 📂

* **DE (arch/impl/evol)**: [evaluation/benchmarks/dacomp/data/dacomp_de](evaluation/benchmarks/dacomp/data/dacomp_de) (en) and [dacomp_de_zh](evaluation/benchmarks/dacomp/data/dacomp_de_zh) (zh)

Please copy the data to the target folder.
```
cp -R ../../dacomp-de/tasks/. evaluation/benchmarks/dacomp/data/dacomp_de/
cp -R ../../dacomp-de/tasks_zh/. evaluation/benchmarks/dacomp/data/dacomp_de_zh/
```

```
dacomp_de/
  ├── dacomp-de-arch-001/
  ├── …
  ├── dacomp-de-evol-001/
  ├── …
  └── dacomp-de-impl-001/
```

* **DA (analysis)**: [evaluation/benchmarks/dacomp/data/dacomp_da](evaluation/benchmarks/dacomp/data/dacomp_da) (en) and [dacomp_da_zh](evaluation/benchmarks/dacomp/data/dacomp_da_zh) (zh)

Please copy the data to the target folder.
```
cp -R ../../dacomp-da/tasks/. evaluation/benchmarks/dacomp/data/dacomp_da/
cp -R ../../dacomp-da/tasks_zh/. evaluation/benchmarks/dacomp/data/dacomp_da_zh/
```

```
dacomp_da/
  ├── dacomp-001/dacomp-001.sqlite
  ├── …
  └── dacomp-da.jsonl
```

## 3. Scripts Overview 🔧 (Run from the Repository Root)

All scripts log outputs to `evaluation_output/.../logs/` under their respective directories.

### DE Single-Agent (impl/evol) 🤖

Command:

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_de.sh \
  <LLM_CONFIG> "" CodeActAgent <NUM_TASKS> <NUM_WORKERS> <TASK_IDS> <SKIP> \
  <LANG> <PROMPT_LANG> <TASK_TYPE> <EXP_NAME> <OVERWRITE_FLAG>
```

* **LANG**: `zh`/`en` (Selects the dataset folder).
* **PROMPT_LANG**: `zh`/`en`.
* **TASK_TYPE**: `impl` / `evol` / `all`.
* **EXP_NAME**: Custom experiment tag for naming the output directory.
* **OVERWRITE_FLAG**: Any non-empty value enables `--overwrite`.
* **Outputs**: `evaluation_output/dacomp_de_impl|evol/<model>_<exp>[_zh]/`.

Examples:

* For `impl`, using Chinese data/prompt with overwrite:

  ```bash
  bash evaluation/benchmarks/dacomp/scripts/run_infer_de.sh llm.gpt-5-2025-08-07-eval "" CodeActAgent 2 1 "" 0 zh zh impl myexp 1
  ```
* For all task types, using English data/prompt with no overwrite:

  ```bash
  bash evaluation/benchmarks/dacomp/scripts/run_infer_de.sh llm.gpt-5-2025-08-07-eval "" CodeActAgent 4 1 "" 0 en en all expA
  ```

### DE Multi-Agent (impl only) 🤝

1. Download `plan_config.zip` from:
   [plan_config.zip](https://drive.google.com/file/d/1Wi3MOiReNH9m_jtv81tR8-pzVeBZxq09/view?usp=drive_link)

2. Run the script below to unzip it and move each `build_plan.yaml` into the corresponding task folder:

```bash
#!/bin/bash
unzip plan_config.zip -d ./plan

target_base_path="/path/to/target/directory" # evaluation/benchmarks/dacomp/data/dacomp_de 

for task_folder in ./plan/dacomp-de-impl-*; do
  if [ -f "$task_folder/build_plan.yaml" ]; then
    task_name=$(basename "$task_folder")
    dest_folder="$target_base_path/$task_name"
    mkdir -p "$dest_folder"
    mv "$task_folder/build_plan.yaml" "$dest_folder/"
    echo "Moved build_plan.yaml to $dest_folder"
  else
    echo "No build_plan.yaml found in $task_folder"
  fi
done
```


3. Start:

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_de_multi_agent_impl.sh \
  <LLM_CONFIG> "" CodeActAgent <NUM_TASKS> <NUM_WORKERS> <TASK_IDS> <SKIP> \
  <LANG> <PROMPT_LANG> impl <AGENTS_CONFIG> <EXP_NAME> <OVERWRITE_FLAG>
```

* **AGENTS_CONFIG**: Path to `build_plan.yaml`/`agents.yaml` or empty for auto-config (per-project).
* **Outputs**: `evaluation_output/dacomp_de_impl_multi_agent/<model>_<exp>[_zh]/`.

Example:

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_de_multi_agent_impl.sh llm.gpt-5-2025-08-07-eval "" CodeActAgent 3 1 "" 0 zh zh impl "" myexp 1
```

### DE-Arch (Modeling Spec Generation) 📐

Command:

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_de_arch.sh \
  <MODEL> <PARALLEL> <TASKS_SPEC> <EXP_NAME> <OVERWRITE_FLAG> <LANG_FILTER> \
  <DATA_EN> <DATA_ZH> <OUTPUT_BASE>
```

* **MODEL**: Key in `SUPPORTED_MODELS` (as defined in `run_infer_de_arch.py`).
* **LANG_FILTER**: `all` / `zh` / `en` to run tasks only for that language.
* Defaults for data roots and output base resolve to `evaluation/benchmarks/dacomp/data/dacomp_de[_zh]` and `evaluation_output/dacomp_de_arch/`.

Example (for Chinese only, with overwrite):

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_de_arch.sh gpt-4o-2024-11-20 8 all myexp 1 zh
```

### DA (Data Analysis) 📊

Command:

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_da.sh \
  <LLM_CONFIG> "" CodeActAgent <NUM_TASKS> <NUM_WORKERS> <TASK_IDS> <SKIP> \
  <DATA_TYPE> <PROMPT_LANG> <EXP_NAME> <OVERWRITE_FLAG> <LANG>
```

* **LANG**: `zh`/`en` (Selects between `dacomp_da_zh` and `dacomp_da` datasets).
* **PROMPT_LANG**: `zh`/`en`/`auto` (Auto detects based on task id `-zh-`/`-en-`).
* **Outputs**: `evaluation_output/dacomp_da/<model>_<exp>[_zh]/`.

Example (Chinese dataset, auto-prompt, with overwrite):

```bash
bash evaluation/benchmarks/dacomp/scripts/run_infer_da.sh llm.gpt-5-2025-08-07-eval "" CodeActAgent 3 1 "" 0 sqlite auto myexp 1 zh
```

## 4. Notes ⚠️

* Ensure the `poetry` environment is activated or prefix commands with `poetry run`.
* `--exp-name` appends to output directories; `--overwrite` enables skipping previously completed tasks.
* For DE, using `--task-type all` executes both `impl` and `evol` tasks separately, each with its own logs and output JSONs.

## 5. Thanks 🙌

Powered by the [OpenHands](https://github.com/OpenHands/OpenHands) framework. A huge thank you to the OpenHands community for providing the tooling and agents that make these runners possible. 
