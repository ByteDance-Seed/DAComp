# DA Agent Quickstart

This is the baseline agent used in the paper (three-stage flow for more precise reports). The sibling `spider-agent` is another baseline we use in development; it outputs a single, image-rich report directly. Feel free to refine the system prompts to suit your model and task. Follow these steps to run the DA agent and export results:

1) **Download datasets**  
   First, complete the download in `../dacomp-da/README.md` to obtain:
   - English: `../dacomp-da/tasks/dacomp-da.jsonl`
   - Chinese: `../dacomp-da/tasks_zh/dacomp-da-zh.jsonl`

2) **Configure your LLM**  
   Edit `da_agent/agent/config.py` and fill in your model endpoint, keys, etc.

3) **Install dependencies**  
   ```bash
   pip install -r requirements.txt

   python3 -m pip install -r requirements.txt
   ```


4) **Run the agent**  
   `-s` is the experiment name (output subfolder), `-t` points to the task file.
   ```bash
   # English
   python3 run.py --model openai_qwen3-coder-plus -s test1 -t ../../dacomp-da/tasks/dacomp-da.jsonl
   # Chinese
   python3 run.py --model openai_qwen3-coder-plus -s test1 -t ../../dacomp-da/tasks_zh/dacomp-da-zh.jsonl --language zh
   ```
   Other useful flags:
   - `--example_index`: `all` (default), `0-10`, `2,5` (comma-separated indices)
   - `--example_name`: filter by substring in task id
   - `--language`: `en` (default) or `zh`

5) **Export results to the evaluation suite**  
   Aggregate a run’s outputs into `../dacomp-da/evaluation_suite/agent_results/`:
   ```bash
   python3 get_results.py openai_qwen3-coder-plus-test1 --output_dir ../../dacomp-da/evaluation_suite/agent_results
   python3 get_results.py gemini-2.5-pro-test1 --output_dir ../../dacomp-da/evaluation_suite/agent_results
   ```
