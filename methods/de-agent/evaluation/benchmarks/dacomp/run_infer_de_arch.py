#!/usr/bin/env python3
"""
Unified runner for generating modeling_spec using GPT-4o API
Supports parallel processing and parameter control
"""

import openai
import os
import glob
import re
import time
import argparse
import concurrent.futures
from threading import Lock
from pathlib import Path

from utils.prompt import SYSTEM_PROMPT, SYSTEM_PROMPT_ZH
from utils.model_config import SUPPORTED_MODELS, DEFAULT_MODEL, DEFAULT_BASE_URL

# Default data roots
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_EN = str((BASE_DIR / "data" / "dacomp_de").resolve())
DEFAULT_DATA_ZH = str((BASE_DIR / "data" / "dacomp_de_zh").resolve())
DEFAULT_OUTPUT_BASE = str((BASE_DIR / "evaluation_output" / "dacomp_de_arch").resolve())

# Thread-safe print lock
print_lock = Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print function"""
    with print_lock:
        print(*args, **kwargs)

def find_task_directories(data_dirs):
    """Find all de-arch task directories from given roots."""
    task_dirs = []
    for root in data_dirs:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in root_path.glob("dacomp-de-arch-*"):
            if path.is_dir():
                task_dirs.append(str(path))
    return sorted(task_dirs)

def find_existing_tasks(task_dirs, model_name, output_base, exp_name):
    """Return set of task names that already have outputs."""
    existing = set()
    for task_dir in task_dirs:
        task_name = os.path.basename(task_dir)
        out_path = get_output_file_path(task_dir, model_name, output_base, exp_name)
        if os.path.exists(out_path):
            existing.add(task_name)
    return existing

def read_question_file(task_dir):
    """Read the question content from the task directory"""
    question_files = [f for f in os.listdir(task_dir) if 'question' in f.lower()]
    if question_files:
        question_file = os.path.join(task_dir, question_files[0])
        with open(question_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    else:
        return "Analyze the data and provide business insights for decision making"

def read_data_contract(task_dir):
    """Read the data contract raw file"""
    contract_file = os.path.join(task_dir, "data_contract_raw.yaml")
    if os.path.exists(contract_file):
        with open(contract_file, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        raise FileNotFoundError(f"data_contract_raw.yaml not found in {task_dir}")

def call_gpt_api(question, data_contract, model_name, system_prompt, retries=5, backoff_base=1.0):
    """Call API to generate modeling_spec with specified model, with retries"""
    # Get model configuration
    model_config = SUPPORTED_MODELS.get(model_name, SUPPORTED_MODELS[DEFAULT_MODEL])

    client = openai.AzureOpenAI(
        azure_endpoint=model_config["base_url"],
        api_version=model_config["api_version"],
        api_key=model_config["api_key"],
    )

    prompt = system_prompt.format(
        query=question,
        data_contract=data_contract
    )

    max_tokens = model_config["max_tokens"]

    # Prepare API call parameters
    api_params = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        "max_tokens": max_tokens,
        "extra_headers": {"X-TT-LOGID": ""},
    }

    if model_name == "openai_qwen3-235b-a22b" or model_name == "openai_qwen3-8b":
        api_params["extra_body"] = {
            "stream": False,
            "enable_thinking": False
        }

    last_error = None
    # Total attempts = 1 initial + retries
    for attempt in range(retries + 1):
        try:
            completion = client.chat.completions.create(**api_params)
            return completion.choices[0].message.content
        except Exception as e:
            last_error = str(e)
            if attempt < retries:
                # Exponential backoff: 1s, 2s, 4s, ...
                sleep_seconds = backoff_base * (2 ** attempt)
                try:
                    safe_print(f"   API call failed (attempt {attempt+1}/{retries+1}): {last_error}. Retrying in {sleep_seconds:.1f}s")
                except Exception:
                    pass
                time.sleep(sleep_seconds)
            else:
                break

    return None, last_error

def extract_yaml_content(response):
    """Extract YAML content from the response"""
    # Look for YAML code blocks
    yaml_pattern = r'```yaml\n(.*?)\n```'
    matches = re.findall(yaml_pattern, response, re.DOTALL)

    if matches:
        return matches[0]
    elif 'modeling_spec:' in response:
        return response
    else:
        return response

def get_output_file_path(task_dir, model_name, output_base, exp_name):
    """Return the expected output file path for a task/model combo"""
    task_name = os.path.basename(task_dir)
    return os.path.join(output_base, exp_name, model_name, f"{task_name}.yaml")

def save_data_contract(task_dir, modeling_spec_content, model_name, output_base, exp_name):
    """Save modeling_spec content to results/model_name/task_name.yaml"""
    output_file = get_output_file_path(task_dir, model_name, output_base, exp_name)

    # Ensure directories exist
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(modeling_spec_content)

    return output_file

def _select_prompt(task_dir: str) -> str:
    """Select prompt based on task dir language."""
    name = os.path.basename(task_dir)
    if name.endswith("-zh") or "dacomp_de_zh" in task_dir:
        return SYSTEM_PROMPT_ZH
    return SYSTEM_PROMPT

def process_single_task(task_dir, task_index, total_tasks, model_name, output_base, exp_name, overwrite=False):
    """Process a single task directory"""
    task_name = os.path.basename(task_dir)
    safe_print(f"[{task_index}/{total_tasks}] 📋 {task_name}")

    try:
        output_file = get_output_file_path(task_dir, model_name, output_base, exp_name)

        if not overwrite and os.path.exists(output_file):
            existing_size = os.path.getsize(output_file)
            safe_print(f"   ⏭️  Skipping existing result: {output_file}")
            return True, task_name, existing_size

        # Read question
        question = read_question_file(task_dir)
        safe_print(f"   📝 Question: {question}")

        # Read data contract
        data_contract = read_data_contract(task_dir)
        safe_print(f"   📄 Data contract: {len(data_contract)} chars")

        # Call API
        system_prompt = _select_prompt(task_dir)
        safe_print(f"   🤖 Calling {model_name}...")
        result = call_gpt_api(question, data_contract, model_name, system_prompt, retries=5)

        if isinstance(result, tuple):
            response, error = result
            if response is None:
                safe_print(f"   ❌ API call failed: {error}")
                return False, task_name, error
        else:
            response = result

        if response:
            modeling_spec_content = extract_yaml_content(response)
            output_file = save_data_contract(task_dir, modeling_spec_content, model_name, output_base, exp_name)
            safe_print(f"   ✅ Saved: {output_file} ({len(modeling_spec_content)} chars)")
            return True, task_name, len(modeling_spec_content)
        else:
            safe_print("   ❌ API call failed")
            return False, task_name, "Unknown error"

    except Exception as e:
        safe_print(f"   ❌ Error: {e}")
        return False, task_name, str(e)

def process_tasks_parallel(task_dirs, max_workers, model_name, output_base, exp_name, overwrite):
    """Process tasks in parallel"""
    safe_print(f"🚀 Starting parallel processing with {max_workers} workers using {model_name}")

    results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {
            executor.submit(process_single_task, task_dir, i+1, len(task_dirs), model_name, output_base, exp_name, overwrite): task_dir
            for i, task_dir in enumerate(task_dirs)
        }

        # Collect results as they complete
        for future in concurrent.futures.as_completed(futures):
            task_dir = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                task_name = os.path.basename(task_dir)
                safe_print(f"   ❌ Task {task_name} failed with exception: {e}")
                results.append((False, task_name, str(e)))

    elapsed_time = time.time() - start_time
    return results, elapsed_time

def process_tasks_sequential(task_dirs, model_name, output_base, exp_name, overwrite):
    """Process tasks sequentially"""
    safe_print(f"🚀 Starting sequential processing using {model_name}")

    results = []
    start_time = time.time()

    for i, task_dir in enumerate(task_dirs, 1):
        result = process_single_task(task_dir, i, len(task_dirs), model_name, output_base, exp_name, overwrite)
        results.append(result)

        # Add small delay to avoid overwhelming the API
        if i < len(task_dirs):
            time.sleep(1)

    elapsed_time = time.time() - start_time
    return results, elapsed_time

def print_summary(results, elapsed_time, total_tasks):
    """Print processing summary"""
    success_count = sum(1 for success, _, _ in results if success)

    safe_print(f"\n{'='*60}")
    safe_print(f"🎯 Processing Summary:")
    safe_print(f"   ✅ Success: {success_count}/{total_tasks} tasks")
    safe_print(f"   ⏱️  Total time: {elapsed_time:.1f} seconds")
    safe_print(f"   📊 Rate: {total_tasks/elapsed_time*60:.1f} tasks/minute")

    # Show failed tasks
    failed_tasks = [(name, error) for success, name, error in results if not success]
    if failed_tasks:
        safe_print(f"\n❌ Failed tasks:")
        for name, error in failed_tasks:
            safe_print(f"   - {name}: {error}")

    # Show successful tasks with sizes
    successful_tasks = [(name, size) for success, name, size in results if success]
    if successful_tasks:
        safe_print(f"\n✅ Successful tasks:")
        for name, size in successful_tasks:
            safe_print(f"   - {name}: {size} chars")

def main():
    """Main function with argument parsing"""
    parser = argparse.ArgumentParser(description='Generate modeling_spec for data contracts using various AI models')
    parser.add_argument('--parallel', '-p', type=int, default=10, help='Number of parallel workers (default: 10)')
    parser.add_argument('--tasks', '-t', type=str, default='all', help='Specific task number (1-N) or "all" (default: all)')
    parser.add_argument('--model', '-m', type=str, default=DEFAULT_MODEL, choices=list(SUPPORTED_MODELS.keys()),  help=f'Model to use (default: {DEFAULT_MODEL})')
    parser.add_argument('--list-models', action='store_true', help='List all supported models and exit')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed without actually running')
    parser.add_argument('--overwrite', action='store_true', help='Re-run tasks even if their output files already exist')
    parser.add_argument('--data-en', type=str, default=DEFAULT_DATA_EN, help='English task data root (default: %(default)s)')
    parser.add_argument('--data-zh', type=str, default=DEFAULT_DATA_ZH, help='Chinese task data root (default: %(default)s)')
    parser.add_argument('--output-base', type=str, default=DEFAULT_OUTPUT_BASE, help='Base output directory (default: %(default)s)')
    parser.add_argument('--exp-name', type=str, default="default", help='Experiment name to group outputs (default: default)')
    parser.add_argument('--lang-filter', choices=['all', 'zh', 'en'], default='all', help='Run only zh tasks, en tasks, or all (default: all)')

    args = parser.parse_args()

    # Handle list models request
    if args.list_models:
        safe_print("📋 Supported models:")
        for model, config in SUPPORTED_MODELS.items():
            default_mark = " (default)" if model == DEFAULT_MODEL else ""
            url_info = f" | URL: {config['base_url']}" if config['base_url'] != DEFAULT_BASE_URL else ""
            safe_print(f"   - {model}: max_tokens={config['max_tokens']}{url_info}{default_mark}")
        return

    output_base = os.path.abspath(args.output_base)

    # Validate model
    if args.model not in SUPPORTED_MODELS:
        safe_print(f"❌ Unsupported model: {args.model}")
        safe_print(f"   Supported models: {', '.join(SUPPORTED_MODELS.keys())}")
        return

    # Find all task directories (de-arch only)
    data_roots = [args.data_en, args.data_zh]
    all_task_dirs = find_task_directories(data_roots)

    if not all_task_dirs:
        safe_print("❌ No task directories found!")
        return

    # Language filter if requested
    if args.lang_filter == 'zh':
        all_task_dirs = [d for d in all_task_dirs if d.endswith('-zh') or 'dacomp_de_zh' in d]
        if not all_task_dirs:
            safe_print("❌ No zh tasks found under provided data roots!")
            return
    elif args.lang_filter == 'en':
        all_task_dirs = [d for d in all_task_dirs if not (d.endswith('-zh') or 'dacomp_de_zh' in d)]
        if not all_task_dirs:
            safe_print("❌ No en tasks found under provided data roots!")
            return

    # Filter tasks if specific task requested
    if args.tasks != 'all':
        try:
            task_num = int(args.tasks)
            if 1 <= task_num <= len(all_task_dirs):
                task_dirs = [all_task_dirs[task_num - 1]]
                safe_print(f"📁 Processing specific task: {os.path.basename(task_dirs[0])}")
            else:
                safe_print(f"❌ Invalid task number: {task_num}. Must be between 1 and {len(all_task_dirs)}")
                return
        except ValueError:
            safe_print(f"❌ Invalid task specification: {args.tasks}")
            return
    else:
        task_dirs = all_task_dirs
        safe_print(f"📁 Found {len(task_dirs)} task directories")

    if args.dry_run:
        safe_print("\n🔍 Dry run - would process:")
        for i, task_dir in enumerate(task_dirs, 1):
            safe_print(f"   {i}. {os.path.basename(task_dir)}")
        safe_print(f"\nConfiguration:")
        safe_print(f"   Model: {args.model}")
        safe_print(f"   Max tokens: {SUPPORTED_MODELS[args.model]['max_tokens']}")
        safe_print(f"   Parallel workers: {args.parallel}")
        safe_print(f"   Processing mode: {'Parallel' if args.parallel > 1 else 'Sequential'}")
        safe_print(f"   Overwrite existing results: {args.overwrite}")
        safe_print(f"   Output base: {args.output_base}")
        safe_print(f"   Experiment name: {args.exp_name}")
        safe_print(f"   Skip completed: {not args.overwrite}")
        safe_print(f"   Language filter: {args.lang_filter}")
        return

    if not args.overwrite:
        existing = find_existing_tasks(task_dirs, args.model, output_base, args.exp_name)
        if existing:
            safe_print(f"   ⏭️  Skipping {len(existing)} completed tasks: {', '.join(sorted(existing))}")
        task_dirs = [d for d in task_dirs if os.path.basename(d) not in existing]

    if not task_dirs:
        safe_print("✅ All tasks already completed or skipped; nothing to run.")
        return

    # Process tasks
    if args.parallel > 1:
        results, elapsed_time = process_tasks_parallel(task_dirs, args.parallel, args.model, output_base, args.exp_name, args.overwrite)
    else:
        results, elapsed_time = process_tasks_sequential(task_dirs, args.model, output_base, args.exp_name, args.overwrite)

    # Print summary
    print_summary(results, elapsed_time, len(task_dirs))

if __name__ == "__main__":
    main()
