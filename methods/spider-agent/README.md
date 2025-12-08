# Spider Agent Quickstart

This is the sibling baseline we use during development; it produces a single, image-rich report (contrast with `da-agent`, which uses a three-stage flow for tighter control). You can (and should) refine the system prompts to better guide your model for your use case.

1) **Download datasets**  
   Follow `../dacomp-da/README.md` to download:
   - English: `../dacomp-da/tasks/dacomp-da.jsonl`
   - Chinese: `../dacomp-da/tasks_zh/dacomp-da-zh.jsonl`

2) **Configure your LLM**  
   Update model endpoints/keys in `spider_agent/agent/config.py` as needed.

3) **Install dependencies**  
   ```bash
   pip install -r requirements.txt

   python3 -m pip install -r requirements.txt
   ```

4) **Run the agent**  
   `-s` sets the experiment suffix (output subfolder), `-t` points to the task JSONL.
   ```bash
   # English example
   python3 run.py --model openai_qwen3-coder-plus -s both1 -t ../../dacomp-da/tasks/dacomp-da.jsonl --image_prompt
   # Chinese example
   python3 run.py --model openai_qwen3-coder-plus -s try1-zh -t ../../dacomp-da/tasks_zh/dacomp-da-zh.jsonl --language zh --image_prompt
   ```
Common flags:
- `--example_index`: index range (e.g., `0-10`, `2,3`, or `all`)
- `--example_name`: filter by substring in task id
- `--language`: `zh` (default) or `en`
- `--image_prompt`: enable image-enhanced prompt for design tasks
- `--overwriting` / `--retry_failed`: control reruns when outputs exist

5) **Export results to the evaluation suite**  
   Collect a run’s outputs into `../dacomp-da/evaluation_suite/agent_results/`:
   ```bash
   python3 get_results.py openai_qwen3-coder-plus-test1-zh --output_dir ../../dacomp-da/evaluation_suite/agent_results
   python3 get_results.py gemini-2.5-pro-both1 --output_dir ../../dacomp-da/evaluation_suite/agent_results
   ```
