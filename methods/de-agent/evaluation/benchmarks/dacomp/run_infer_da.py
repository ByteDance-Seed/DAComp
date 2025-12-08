import asyncio
import json
import os
import inspect
import subprocess
import time, random
import shutil
import argparse
from typing import Any, List, Optional, Union

import pandas as pd
import numpy as np
from tqdm import tqdm

from datetime import datetime
from openhands.llm.llm_registry import LLMRegistry

from evaluation.utils.shared import (
    EvalMetadata,
    EvalOutput,
    compatibility_for_eval_history_pairs,
    get_default_sandbox_config_for_eval,
    make_metadata,
    prepare_dataset,
    reset_logger_for_multiprocessing,
    run_evaluation,
)
from openhands.controller.state.state import State
from openhands.core.config import (
    OpenHandsConfig,
    get_llm_config_arg,
    parse_arguments,
)
from openhands.core.logger import openhands_logger as logger
from openhands.core.main import create_runtime, run_controller
from openhands.events.action import CmdRunAction, MessageAction
from openhands.events.observation import CmdOutputObservation
from openhands.runtime.base import Runtime
from openhands.utils.async_utils import call_async_from_sync


def _render_prompt_candidates(candidates: list[str]) -> str:
    for tpl in candidates:
        content = _render_prompt_template(tpl)
        if content:
            return content
    return ""


def get_system_prompt_by_lang(lang: str) -> str:
    if lang == 'zh':
        return _render_prompt_candidates(['system_prompt_da.j2'])
    return _render_prompt_candidates(['system_prompt_da_en.j2'])


def _resolve_da_paths(lang: Optional[str] = None) -> str:
    """Resolve DA task data root by language preference."""
    base = os.path.join(os.path.dirname(__file__), 'data')
    lang = (lang or os.getenv("DATAAGENT_LANG", "zh")).lower()
    preferred = ['dacomp_da_zh', 'dacomp_da'] if lang.startswith('zh') else ['dacomp_da', 'dacomp_da_zh']
    for d in preferred:
        candidate = os.path.join(base, d)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(base, preferred[0])


def auto_detect_language_from_task_id(task_id: str) -> str:
    """Auto-detect language from task ID.

    Args:
        task_id: Task ID like 'dacomp-da-zh-001' or 'dacomp-da-002'

    Returns:
        'zh' for Chinese tasks, 'en' for English tasks
    """
    if '-zh-' in task_id:
        return 'zh'
    elif '-en-' in task_id:
        return 'en'
    else:
        return 'zh'


def make_codeact_user_response(lang: str):
    zh = (
        '请继续按照你认为合适的方法完成该任务。\n'
        '如果你认为已经完成，请使用 "finish" 工具输出分析报告，以 【回复用户】 开头，例如：【回复用户】您刚才询问的问题我已经帮你查到结果啦。\n'
        '重要：你绝不能请求人类帮助，也不要使用互联网来解决此任务。\n'
    )
    en = (
        'Please continue with the approach you think is appropriate to complete the task.\n'
        'When you believe the task is completed, call the "finish" tool and put the full report in the message, starting with 【Reply to user】.\n'
        'Important: Do not ask a human for help and do not use the Internet for this task.\n'
    )
    template = zh if lang == 'zh' else en

    def responder(state: State) -> str:
        return template
    return responder

def _guidelines_block(lang: str) -> str:
    if lang == 'zh':
        return (
            '\n\n## 重要指南：\n'
            '- 所有文件都位于当前工作目录（运行 `ls -la .` 查看）\n'
            '- 开始前先执行 `ls -la .` 查看可用文件\n\n'
            '重要：你只能与提供的环境交互，绝不要请求人类帮助。\n'
            '你需要分析提供的文件，编写必要代码，并按要求保存结果。\n'
            '先列出工作区文件以明确可用的精确路径。\n'
        )
    return (
        '\n\n## Important Guidelines:\n'
        '- All files live in the current workspace directory (run `ls -la .`)\n'
        '- Run `ls -la .` first to see available files\n\n'
        'Important: You can only interact with the provided environment. Do not ask a human for help.\n'
        'Analyze the provided files, write necessary code, and save outputs as required.\n'
        'List the workspace files first to confirm exact file paths.\n'
    )

AGENT_SUFFIX_BY_LANG = {
    'zh': '当你认为已完成任务时，必须使用 "finish" 工具输出分析报告，以【回复用户】开头。例如：【回复用户】您刚才询问的问题我已经帮你查到结果啦。\n若仍需继续分析或整理内容，请不要调用 "finish"，继续完善后再一次性提交最终报告。',
    'en': 'When you believe the task is completed, you must call the "finish" tool to output the final analysis report, starting with 【 Reply to user 】. If you still need to analyze or organize further, do not call "finish"; continue and submit a single complete report later.',
}


def get_config(
    metadata: EvalMetadata,
    workspace_base: Optional[str] = None,
) -> OpenHandsConfig:
    """Configure the OpenHands environment for dataagent tasks."""
    sandbox_config = get_default_sandbox_config_for_eval()

    config = OpenHandsConfig(
        default_agent=metadata.agent_class,
        run_as_openhands=False,
        runtime='cli',
        max_iterations=metadata.max_iterations,
        sandbox=sandbox_config,
        workspace_base=workspace_base,
        enable_browser=False,
    )
    config.set_llm_config(metadata.llm_config)
    agent_config = config.get_agent_config(metadata.agent_class)
    agent_config.enable_prompt_extensions = False
    agent_config.enable_jupyter = False
    agent_config.enable_browsing = False
    return config


def _get_thought(evt: dict) -> Optional[str]:
    try:
        args = evt.get("args") or {}
        thought = args.get("thought")
        if thought is None:
            thought = evt.get("thought") or args.get("reasoning") or args.get("plan")
        return thought
    except Exception:
        return None

def _is_zh(text: Optional[str]) -> bool:
    if not text:
        return False
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)

def _prompts_dir() -> str:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    return os.path.join(root, 'openhands', 'agenthub', 'codeact_agent', 'prompts')

def _render_prompt_template(filename: str) -> str:
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape  # type: ignore
        env = Environment(
            loader=FileSystemLoader(_prompts_dir()),
            autoescape=select_autoescape(enabled_extensions=('j2',)),
            enable_async=False,
        )
        tmpl = env.get_template(filename)
        return (tmpl.render() or "").strip()
    except Exception:
        try:
            with open(os.path.join(_prompts_dir(), filename), 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            return ""

def get_system_prompt_fallback(instruction: str) -> str:
    if _is_zh(instruction):
        return _render_prompt_candidates(['system_prompt_da.j2'])
    return _render_prompt_candidates(['system_prompt_da_en.j2'])

def extract_text(evt: dict) -> str:
    if not isinstance(evt, dict):
        return ""
    return (evt.get("content") or evt.get("message") or "").strip()

def simplify_histories(histories) -> list[dict]:
    simplified: list[dict] = []
    step_no = 1
    skipped_first_user_message = False

    def add_message(evt: dict, action: str, role: str, include_thought: bool = True):
        nonlocal step_no
        entry = {
            "step": step_no,
            "role": role,
            "action": action,
            "content": (evt.get("message") or evt.get("content") or ""),
        }
        if include_thought:
            entry["thought"] = _get_thought(evt)
        simplified.append(entry)
        step_no += 1

    def add_tool(evt_req: dict, evt_res: Optional[dict], tool_name: str, req_key: str, res_key: str = "output"):
        nonlocal step_no
        args = evt_req.get("args") or {}
        request_payload = {}
        if req_key in args:
            request_payload[req_key] = args.get(req_key)
        else:
            key = "command" if "command" in args else ("code" if "code" in args else None)
            if key:
                request_payload[key] = args.get(key)

        result_payload = {}
        if evt_res:
            out_text = evt_res.get("content") or evt_res.get("message") or ""
            if out_text != "":
                result_payload[res_key] = out_text
            try:
                meta = (evt_res.get("extras") or {}).get("metadata") or {}
                exit_code = meta.get("exit_code")
                if exit_code is not None:
                    result_payload["exit_code"] = exit_code
            except Exception:
                pass

        simplified.append({
            "step": step_no,
            "role": "assistant",
            "action": tool_name,
            "request": request_payload or None,
            "result": result_payload or None,
            "thought": _get_thought(evt_req),
        })
        step_no += 1

    ALLOWED = {"message", "run", "run_ipython", "ipython", "browser", "finish"}

    for group in histories or []:
        if not isinstance(group, (list, tuple)) or len(group) == 0:
            continue
        evt0 = group[0] or {}
        evt1 = group[1] if len(group) > 1 else None

        action = (evt0.get("action") or "").strip()
        if action not in ALLOWED:
            continue

        src = (evt0.get("source") or "").lower()
        if action == "message":
            if src == "user" and not skipped_first_user_message:
                skipped_first_user_message = True
                continue
            role = "user" if src == "user" else "assistant"
            add_message(evt0, "message", role)
            continue
        if action == "run":
            add_tool(evt0, evt1, "execute_bash", req_key="command", res_key="output")
            continue
        if action in ("run_ipython", "ipython"):
            add_tool(evt0, evt1, "execute_ipython_cell", req_key="code", res_key="output")
            continue
        if action == "browser":
            add_tool(evt0, evt1, "browser", req_key="code", res_key="output")
            continue
        if action == "finish":
            add_message(evt0, "finish", "assistant", include_thought=False)
            continue

    return simplified

def read_result_md(runtime: Runtime, max_chars: int = 200000) -> str:
    try:
        candidate_paths = ["./result.md", "result.md"]
        for candidate in candidate_paths:
            check = runtime.run_action(CmdRunAction(
                command='python - << "PY"\n'
                        'import os\n'
                        f'path = r"""{candidate}"""\n'
                        'print("OK" if (os.path.exists(path) and os.path.getsize(path)>0) else "MISS")\n'
                        'PY'
            ))
            if "OK" not in (check.content or ""):
                continue
            read = runtime.run_action(CmdRunAction(
                command='python - << "PY"\n'
                        f'path = r"""{candidate}"""\n'
                        f'print(open(path,"r",encoding="utf-8",errors="ignore").read()[:{max_chars}])\n'
                        'PY'
            ))
            return (read.content or "").strip()
        return ""
    except Exception:
        return ""

def build_summary(simplified_trajectory: list[dict]) -> dict:
    total = len(simplified_trajectory or [])
    tool_calls = sum(1 for s in simplified_trajectory if s.get("action") in ("execute_bash", "execute_ipython_cell", "browser"))
    bash_calls = sum(1 for s in simplified_trajectory if s.get("action") == "execute_bash")
    ipython_calls = sum(1 for s in simplified_trajectory if s.get("action") == "execute_ipython_cell")
    finish_calls = sum(1 for s in simplified_trajectory if s.get("action") == "finish")


    return {
        "total_steps": total,
        "tool_calls": tool_calls,
        "bash_calls": bash_calls,
        "ipython_calls": ipython_calls,
        "finish_calls": finish_calls,
    }

def cleanup_runtime_container(runtime: Runtime) -> None:
    if runtime is None:
        return

    for meth in ("shutdown", "close", "stop", "terminate"):
        try:
            fn = getattr(runtime, meth, None)
            if callable(fn):
                if inspect.iscoroutinefunction(fn):
                    call_async_from_sync(fn)
                else:
                    fn()
                logger.info(f"Runtime {meth}() called successfully.")
                break
        except Exception as e:
            logger.warning(f"Runtime {meth}() failed (ignored): {e}")

    container_id = None
    container_name = None
    try:
        container_id = getattr(runtime, "container_id", None) or getattr(runtime, "_container_id", None)
    except Exception:
        pass
    try:
        backend = getattr(runtime, "backend", None)
        if backend and not container_id:
            container_id = getattr(backend, "container_id", None) or getattr(backend, "_container_id", None)
        if backend and not container_name:
            container_name = getattr(backend, "container_name", None) or getattr(backend, "_container_name", None)
    except Exception:
        pass
    try:
        if not container_name:
            container_name = getattr(runtime, "container_name", None) or getattr(runtime, "_container_name", None)
    except Exception:
        pass

    try:
        import docker  # docker SDK
        client = docker.from_env()
        target = None
        if container_id:
            try:
                target = client.containers.get(container_id)
            except Exception:
                target = None
        if target is None and container_name:
            try:
                target = client.containers.get(container_name)
            except Exception:
                target = None
        if target is not None:
            target.remove(force=True)
            ident = target.id[:12] if getattr(target, "id", None) else (container_id or container_name)
            logger.info(f"Removed runtime container via Docker SDK: {ident}")
            return
    except Exception as e:
        logger.warning(f"Docker SDK removal failed (will try CLI if available): {e}")


def load_dataagent_dataset(data_type: str = 'sqlite', lang: str = 'zh'):
    """Load and prepare the dataagent dataset.

    Args:
        data_type: Type of data to use ('sqlite' or 'xlsx')
        lang: Dataset language ('zh' -> dacomp_da_zh, otherwise dacomp_da)
    """
    tasks_root = _resolve_da_paths(lang)
    filename_candidates = ['dacomp-da-zh.jsonl', 'dacomp-da.jsonl'] if str(lang).lower().startswith('zh') else ['dacomp-da.jsonl', 'dacomp-da-zh.jsonl']
    task_config_path = None
    for fname in filename_candidates:
        candidate = os.path.join(tasks_root, fname)
        if os.path.exists(candidate):
            task_config_path = candidate
            break
    if task_config_path is None:
        task_config_path = os.path.join(tasks_root, filename_candidates[0])

    if not os.path.exists(task_config_path):
        logger.error(f"Task config file not found: {task_config_path}")
        raise FileNotFoundError(f"Task config file not found: {task_config_path}")

    if data_type != 'sqlite':
        logger.warning(
            f"Requested data_type='{data_type}', but only sqlite tasks are available. Falling back to sqlite files."
        )
        data_type = 'sqlite'

    tasks: list[dict[str, Any]] = []
    with open(task_config_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    task = json.loads(line)
                    tasks.append(task)
                except json.JSONDecodeError as exc:
                    logger.warning(f"Failed to parse line in {task_config_path}: {exc}")

    logger.info(f"Loaded {len(tasks)} tasks from {task_config_path}")

    if not tasks:
        return pd.DataFrame()

    dataset = pd.DataFrame(tasks)

    id_column = None
    for candidate in ('instance_id', 'id'):
        if candidate in dataset.columns:
            id_column = candidate
            break
    if id_column is None:
        raise KeyError("Task config must include an 'instance_id' or 'id' field.")

    dataset['instance_id'] = dataset[id_column].astype(str)
    dataset['id'] = dataset['instance_id']

    instruction_col = None
    for candidate in ('instruction', 'query'):
        if candidate in dataset.columns:
            instruction_col = candidate
            break
    dataset['instruction'] = dataset[instruction_col].fillna('') if instruction_col else ''
    dataset['query'] = dataset['instruction']

    dataset['data_type'] = 'sqlite'
    dataset['data_file_ext'] = '.sqlite'
    dataset['data_dir'] = dataset['id'].apply(lambda task_id: os.path.join(tasks_root, task_id))

    missing_files: list[str] = []
    for _, row in dataset.iterrows():
        data_dir = row['data_dir']
        data_file = os.path.join(data_dir, row['id'] + row['data_file_ext'])
        if not os.path.exists(data_file):
            missing_files.append(data_file)

    if missing_files:
        logger.warning(f"Missing {len(missing_files)} data files: {missing_files[:5]}...")
    else:
        logger.info(f"All {len(dataset)} data files found in {tasks_root}")

    return dataset


def create_task_prompt(instance: pd.Series, lang: str) -> str:
    """Create a prompt for the dataagent task."""
    instruction_text = (
        instance.get('instruction')
        or instance.get('query')
        or ''
    )
    task_id = instance['id']
    data_type = instance['data_type']
    data_file_ext = instance['data_file_ext']

    prompt = ""

    if lang == 'zh':
        prompt += (
            "你是一名专业的数据分析师。你的主要目标就是根据提供给你的问题和数据，进行分析和推理,不要答非所问，严格按照问题的要求。最终提供一个分析报告，写成一个markdown文件保存，里面可以包含图片。"
            f"## 问题描述：\n{instruction_text}\n\n"
        )
    else:
        prompt += (
            "You are a professional data analyst. Your primary goal is to conduct analysis and reasoning based on the questions and data provided to you. Do not provide irrelevant answers; strictly follow the requirements of the question. Ultimately, provide an analysis report saved as a Markdown file, which may include images."
            f"## Problem Description:\n{instruction_text}\n\n"
        )

    data_file_name = f"{task_id}{data_file_ext}"

    if lang == 'zh':
        prompt += "## 工作区中可用的文件：\n\n"
        prompt += "**重要的文件路径说明：**\n"
        prompt += "- 所有文件均位于当前工作目录（`./`）\n"
        prompt += "- 访问文件时请使用相对路径，例如 `./文件名`\n"
        prompt += "### 数据文件：\n"
        prompt += f"- `./{data_file_name}` "
        prompt += "(SQLite数据库文件)\n" if data_type == 'sqlite' else "(Excel文件)\n"
    else:
        prompt += "## Files available in the workspace:\n\n"
        prompt += "**Important path notes:**\n"
        prompt += "- All files are under the current working directory (`./`)\n"
        prompt += "- Use exact relative paths such as `./filename`\n"
        prompt += "### Data file:\n"
        prompt += f"- `./{data_file_name}` "
        prompt += "(SQLite database file)\n" if data_type == 'sqlite' else "(Excel file)\n"

    if lang == 'zh':
        prompt += "\n### 数据访问示例：\n```python\n"
        if data_type == 'sqlite':
            prompt += "import sqlite3\nimport pandas as pd\n\n"
            prompt += f"# 连接SQLite数据库\nconn = sqlite3.connect('./{data_file_name}')\n"
            prompt += "# 查看所有表\n"
            prompt += "tables = pd.read_sql(\"SELECT name FROM sqlite_master WHERE type='table'\", conn)\n"
            prompt += "# 读取数据\ndf = pd.read_sql('SELECT * FROM table_name', conn)\n"
        else:
            prompt += "import pandas as pd\n\n"
            prompt += f"# 读取Excel文件\ndf = pd.read_excel('./{data_file_name}')\n"
            prompt += f"# 如果有多个工作表\ndf = pd.read_excel('./{data_file_name}', sheet_name='sheet_name')\n"
        prompt += "```\n"
    else:
        prompt += "\n### Data access examples:\n```python\n"
        if data_type == 'sqlite':
            prompt += "import sqlite3\nimport pandas as pd\n\n"
            prompt += f"# Connect to SQLite database\nconn = sqlite3.connect('./{data_file_name}')\n"
            prompt += "# List all tables\n"
            prompt += "tables = pd.read_sql(\"SELECT name FROM sqlite_master WHERE type='table'\", conn)\n"
            prompt += "# Read data\ndf = pd.read_sql('SELECT * FROM table_name', conn)\n"
        else:
            prompt += "import pandas as pd\n\n"
            prompt += f"# Read Excel file\ndf = pd.read_excel('./{data_file_name}')\n"
            prompt += f"# If multiple sheets\ndf = pd.read_excel('./{data_file_name}', sheet_name='sheet_name')\n"
        prompt += "```\n"

    if lang == 'zh':
        prompt += (
            "\n## 输出要求（重要）：\n"
            "- 当分析完成后，请将完整最终报告写入文件 `./result.md`（Markdown，包含：标题/方法或数据依据/分析/结论与建议）。\n"
            "- 完成时仍需调用 finish；推荐将报告要点同步写入 finish.message。\n"
        )
    else:
        prompt += (
            "\n## Output requirements (important):\n"
            "- After finishing the analysis, write the full final report to `./result.md` (Markdown, including: Title / Method or Data Basis / Analysis / Conclusions & Recommendations).\n"
            "- You still need to call the finish tool; it is recommended to also put the report content into finish.message.\n"
        )

    return prompt


def prepare_workspace(
    instance: pd.Series,
    task_output_dir: str,
) -> str:
    """Prepare workspace by creating a task-specific directory and copying the data file."""
    logger.info(f'{"=" * 50} BEGIN Workspace Preparation {"=" * 50}')

    task_id = instance['id']
    data_dir = instance['data_dir']
    data_file_ext = instance['data_file_ext']

    # Create task output directory
    task_output_dir = os.path.abspath(task_output_dir)
    os.makedirs(task_output_dir, exist_ok=True)

    if not os.path.isdir(data_dir):
        logger.error(f"Source data directory not found: {data_dir}")
        raise FileNotFoundError(f"Source data directory not found: {data_dir}")

    # Copy the data file to the workspace
    source_file = os.path.join(data_dir, task_id + data_file_ext)
    dest_file = os.path.join(task_output_dir, task_id + data_file_ext)

    if not os.path.exists(source_file):
        logger.error(f"Source data file not found: {source_file}")
        raise FileNotFoundError(f"Source data file not found: {source_file}")

    try:
        shutil.copy2(source_file, dest_file)
        logger.info(f"Copied data file: {task_id + data_file_ext}")
    except Exception as e:
        logger.error(f"Failed to copy data file: {e}")
        raise

    # List copied files for verification
    logger.info(f"Files in workspace: {os.listdir(task_output_dir)}")

    logger.info(f'{"=" * 50} END Workspace Preparation {"=" * 50}')
    return task_output_dir


def initialize_runtime(
    runtime: Runtime,
    instance: pd.Series,
):
    """Initialize the runtime environment for the dataagent task."""
    logger.info(f'{"-" * 50} BEGIN Runtime Initialization Fn {"-" * 50}')
    obs: CmdOutputObservation

    # Verify workspace is mounted correctly
    list_cmd = 'ls -la .'
    obs = runtime.run_action(CmdRunAction(command=list_cmd))
    logger.info(f"Workspace contents (mounted): {obs.content}")

    # Skip package installation - assuming all required packages are already available in the host environment
    # (pandas, numpy, scipy, matplotlib, seaborn, openpyxl, sqlalchemy, xlrd, statsmodels, wordcloud, nltk, scikit-learn, plotly, etc.)
    logger.info("Skipping package installation - assuming all required packages exist in the host environment")

    # Verify data file exists in workspace
    task_id = instance['id']
    data_file_ext = instance['data_file_ext']
    data_file = f"./{task_id}{data_file_ext}"

    obs = runtime.run_action(CmdRunAction(command=f'ls -la "{data_file}" 2>/dev/null || echo "Data file not found"'))
    if "Data file not found" in obs.content:
        logger.warning(f"Data file verification failed for: {data_file}")
    else:
        logger.info(f"Data file verified: {data_file}")

    logger.info(f'{"-" * 50} END Runtime Initialization Fn {"-" * 50}')


def create_evaluator_compatible_structure(
    instance_id: str,
    output: EvalOutput,
    metadata: EvalMetadata,
    runtime: Runtime,
    source_dir: str,
    final_text: Optional[str] = None,
    system_prompt_text: Optional[str] = None,
):
    """Create the file structure for storing task outputs."""
    task_output_dir = os.path.join(metadata.eval_output_dir, instance_id)
    os.makedirs(task_output_dir, exist_ok=True)

    result_md_content = (final_text or "").strip()
    try:
        md_from_file = read_result_md(runtime)
        if md_from_file:
            result_md_content = md_from_file
            logger.info("Using result.md content for result.json")
        else:
            logger.info("No result.md or empty; fallback to final_text for result.json")
    except Exception as e:
        logger.warning(f"Failed to read result.md, fallback to final_text: {e}")

    # system_prompt_text = get_system_prompt_fallback(output.instruction or "")

    if not system_prompt_text:
        pl = os.getenv("DATAAGENT_PROMPT_LANG", "zh").lower()
        system_prompt_text = get_system_prompt_by_lang(pl)

    try:
        simplified_traj = simplify_histories(output.history or [])
        summary = build_summary(simplified_traj)
    except Exception as e:
        logger.warning(f"Failed to simplify trajectory: {e}")
        simplified_traj, summary = [], {}

    result_file = os.path.join(task_output_dir, 'result.json')
    result_data = {
        "instance_id": output.instance_id,
        "instruction": output.instruction,
        "status": "success" if (output.error is None) else "error",
        "error": (str(output.error) if output.error else None),
        "result": result_md_content,
        "system_prompt": system_prompt_text or "",
        "summary": summary,
        "trajectory": simplified_traj,
    }
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    if os.path.exists(source_dir):
        for filename in os.listdir(source_dir):
            src_path = os.path.join(source_dir, filename)
            dst_path = os.path.join(task_output_dir, filename)
            if os.path.isfile(src_path):
                shutil.copy2(src_path, dst_path)
                logger.info(f"Copied source file: {filename}")

    logger.info(f"Created task output structure at: {task_output_dir}")
    return task_output_dir


def process_instance(
    instance: pd.Series,
    metadata: EvalMetadata,
    reset_logger: bool = True,
) -> EvalOutput:
    """Process a single dataagent task instance."""
    try:
        stagger = float(os.getenv("DATAAGENT_STAGGER_SEC", "2"))
        if stagger > 0:
            time.sleep(random.random() * stagger)
    except Exception:
        pass

    instance_id = instance['id']

    # Auto-detect language from task ID, fallback to environment variable
    auto_detected_lang = auto_detect_language_from_task_id(instance_id)
    env_prompt_lang = os.getenv("DATAAGENT_PROMPT_LANG", "auto").lower()

    # Use auto-detected language if environment variable is "auto", otherwise use environment variable
    if env_prompt_lang == "auto":
        prompt_lang = auto_detected_lang
    else:
        prompt_lang = env_prompt_lang

    logger.info(f"Task {instance_id}: Auto-detected language = {auto_detected_lang}, Using prompt language = {prompt_lang}")

    config = get_config(metadata)

    # Set up the logger
    if reset_logger:
        log_dir = os.path.join(metadata.eval_output_dir, 'logs')
        reset_logger_for_multiprocessing(logger, instance_id, log_dir)
    else:
        logger.info(f'Starting execution for instance {instance_id}.')

    logger.info(f'Starting execution for instance {instance_id}')

    runtime: Runtime | None = None
    original_cwd = os.getcwd()

    try:
        # Create task output directory and prepare workspace
        task_output_dir = os.path.join(metadata.eval_output_dir, instance_id)
        workspace_path = prepare_workspace(instance, task_output_dir)

        # Ensure workspace_path is absolute
        workspace_path = os.path.abspath(workspace_path)
        logger.info(f"Using absolute workspace path: {workspace_path}")

        # Create config with workspace mounting
        config = get_config(metadata, workspace_path)

        # Create instruction prompt
        instruction = create_task_prompt(instance, prompt_lang)

        instruction += _guidelines_block(prompt_lang)
        instruction += "\n\n" + AGENT_SUFFIX_BY_LANG.get(prompt_lang, AGENT_SUFFIX_BY_LANG['zh'])

        # Create and initialize runtime
        logger.info("Creating runtime...")
        llm_registry = LLMRegistry(config)
        runtime = create_runtime(config, llm_registry)
        call_async_from_sync(runtime.connect)

        logger.info("Initializing runtime...")
        initialize_runtime(runtime, instance)

        # Run the agent
        state: State | None = asyncio.run(
            run_controller(
                config=config,
                initial_user_action=MessageAction(content=instruction),
                # fake_user_response_fn=AGENT_CLS_TO_FAKE_USER_RESPONSE_FN[metadata.agent_class],
                fake_user_response_fn=make_codeact_user_response(prompt_lang),
                runtime=runtime,
            )
        )

        if state is None:
            raise ValueError('State should not be None.')

        # Prepare output
        metrics = state.metrics.get() if state.metrics else None
        histories = compatibility_for_eval_history_pairs(state.history)

        try:
            md_text = read_result_md(runtime)
            if md_text:
                replaced = 0
                for group in (histories or []):
                    if not group:
                        continue
                    evt0 = group[0] or {}
                    if (evt0.get("action") == "finish"):
                        evt0["content"] = md_text
                        evt0["message"] = md_text
                        replaced += 1
                if replaced > 0:
                    logger.info(f"Replaced finish content with result.md for {replaced} finish event(s).")
        except Exception as e:
            logger.warning(f"Failed to replace finish content with result.md: {e}")

        final_text = ""
        try:
            for group in reversed(histories or []):
                evt0 = (group[0] or {})
                if evt0.get("action") == "finish":
                    txt = extract_text(evt0)
                    if txt:
                        final_text = txt
                        break
            if not final_text:
                for group in reversed(histories or []):
                    evt0 = (group[0] or {})
                    if evt0.get("action") == "message" and (evt0.get("source","").lower()=="assistant"):
                        txt = extract_text(evt0)
                        if txt:
                            final_text = txt
                            break
        except Exception as e:
            logger.warning(f"Failed to extract final_text: {e}")

        # system_prompt_text = get_system_prompt_fallback(instruction)
        system_prompt_text = get_system_prompt_by_lang(prompt_lang)

        output = EvalOutput(
            instance_id=instance_id,
            instruction=instruction,
            metadata=metadata,
            history=histories,
            metrics=metrics,
            error=state.last_error if state and state.last_error else None,
            test_result={'result': {'status': 'completed'}, 'metadata': {'task_type': 'Data Insight', 'data_type': instance['data_type']}},
        )

        # Save task results (no source_dir for DI tasks since they only have data files)
        create_evaluator_compatible_structure(
            instance_id,
            output,
            metadata,
            runtime,
            "",  # No source_dir for DI tasks
            final_text=final_text,
            system_prompt_text=system_prompt_text,
        )

        logger.info(f'Task execution completed for instance {instance_id}')
        return output

    except Exception as e:
        logger.error(f"Error processing instance {instance_id}: {e}")

        try:
            task_output_dir = os.path.join(metadata.eval_output_dir, instance_id)
            os.makedirs(task_output_dir, exist_ok=True)

            safe_instruction = locals().get('instruction', "")
            raw_histories = locals().get('histories', [])

            try:
                simplified_traj = simplify_histories(raw_histories or [])
                summary = build_summary(simplified_traj)
            except Exception:
                simplified_traj, summary = [], {}

            with open(os.path.join(task_output_dir, 'result.json'), 'w', encoding='utf-8') as f:
                json.dump({
                    "instance_id": instance_id,
                    "instruction": safe_instruction,
                    "status": "error",
                    "error": str(e),
                    "result": "",
                    "summary": summary,
                    "trajectory": simplified_traj,
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        return EvalOutput(
            instance_id=instance_id,
            instruction="Error occurred before instruction could be created",
            metadata=metadata,
            history=[],
            metrics=None,
            error=str(e),
            test_result={'result': {'status': 'completed'}},
        )

    finally:
        try:
            os.chdir(original_cwd)
        except Exception as e:
            logger.warning(f"Failed to restore working directory to {original_cwd}: {e}")
        try:
            cleanup_runtime_container(runtime)
        except Exception as e:
            logger.warning(f"Post-task per-runtime cleanup failed: {e}")


def prepare_dataset_custom(
    dataset: pd.DataFrame,
    output_file: str,
    eval_n_limit: int,
    eval_ids: list[str] | None = None,
    skip_num: int | None = None,
):
    assert 'instance_id' in dataset.columns, (
        "Expected 'instance_id' column in the dataset."
    )

    logger.info(f'Preparing dataset with {len(dataset)} total instances')

    if eval_ids:
        eval_ids_converted = [str(id) for id in eval_ids]
        dataset = dataset[dataset['instance_id'].isin(eval_ids_converted)]
        logger.info(f'Limiting execution to {len(eval_ids)} specific instances.')
    elif skip_num and skip_num >= 0:
        skip_num = min(skip_num, len(dataset))
        dataset = dataset.iloc[skip_num:]
        logger.info(f'Starting execution with skipping first {skip_num} instances ({len(dataset)} instances to run).')
        if eval_n_limit and eval_n_limit > 0:
            dataset = dataset.head(eval_n_limit)
            logger.info(f'Taking first {eval_n_limit} instances.')
    elif eval_n_limit and eval_n_limit > 0:
        dataset = dataset.head(eval_n_limit)
        logger.info(f'Taking first {eval_n_limit} instances.')

    def make_serializable(instance_dict: dict) -> dict:
        import numpy as np
        for k, v in instance_dict.items():
            if isinstance(v, np.ndarray):
                instance_dict[k] = v.tolist()
            elif isinstance(v, pd.Timestamp):
                instance_dict[k] = str(v)
            elif isinstance(v, dict):
                instance_dict[k] = make_serializable(v)
        return instance_dict

    new_dataset = [
        make_serializable(instance.to_dict())
        for _, instance in dataset.iterrows()
    ]

    logger.info(f'Total instances to process: {len(new_dataset)}')
    return pd.DataFrame(new_dataset)


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description="Run DATAAGENT DA task execution")
    parser.add_argument('-c', '--agent-cls', type=str, default='CodeActAgent', help='Agent class to use')
    parser.add_argument('-l', '--llm-config', type=str, required=True, help='LLM configuration')
    parser.add_argument('-i', '--max-iterations', type=int, default=20, help='Maximum iterations')
    parser.add_argument('-n', '--num-tasks', type=int, default=1, help='Number of tasks to process')
    parser.add_argument('--task-ids', type=str, nargs='+', help='Specific task IDs to process')
    parser.add_argument('--skip-num', type=int, default=0, help='Number of tasks to skip from beginning')
    parser.add_argument('-j', '--concurrency', type=int, default=1, help='Number of parallel workers to run tasks')
    parser.add_argument('--lang', choices=['zh','en'], default='zh', help='Dataset language: zh->dacomp_da_zh, en->dacomp_da')
    parser.add_argument('--prompt-lang', choices=['zh','en','auto'], default='auto',
                        help='Prompt language (system prompt and guidance). "auto" = auto-detect from task IDs')
    parser.add_argument('--data-type', choices=['sqlite','xlsx'], default='sqlite',
                        help='Data type to use: sqlite (SQLite database files) or xlsx (Excel files)')
    parser.add_argument('--exp-name', type=str, default='default', help='Custom experiment name for output directory')
    parser.add_argument('--overwrite', action='store_true', help='Re-run tasks even if a successful result already exists')
    args = parser.parse_args()
    prompt_lang = args.prompt_lang
    dataset_lang = args.lang

    logger.info("Starting DATAAGENT evaluation with parameters:")
    logger.info(f"  Agent: {args.agent_cls}")
    logger.info(f"  LLM Config: {args.llm_config}")
    logger.info(f"  Max Iterations: {args.max_iterations}")
    logger.info(f"  Number of Tasks: {args.num_tasks}")
    logger.info(f"  Skip Number: {args.skip_num}")
    logger.info(f"  Concurrency: {args.concurrency}")
    logger.info(f"  Prompt Lang: {prompt_lang}")
    logger.info(f"  Dataset Lang: {dataset_lang}")
    logger.info(f"  Data Type: {args.data_type}")
    if args.task_ids:
        logger.info(f"  Task IDs: {args.task_ids}")

    # Set environment variable for prompt language
    os.environ["DATAAGENT_LANG"] = dataset_lang
    os.environ["DATAAGENT_PROMPT_LANG"] = prompt_lang

    # Load dataagent dataset
    dataset = load_dataagent_dataset(args.data_type, dataset_lang)

    if dataset.empty:
        logger.error("No tasks found in dataset!")
        exit(1)

    # Set up LLM config
    llm_config = get_llm_config_arg(args.llm_config)
    if llm_config is None:
        raise ValueError(f'Could not find LLM config: --llm_config {args.llm_config}')

    llm_config.modify_params = False

    # Create metadata
    exp_name = (args.exp_name or "default").strip()
    model_name = llm_config.model.split('/')[-1]
    model_path = model_name.replace(':', '_').replace('@', '-')
    lang_suffix = "_zh" if str(dataset_lang).lower().startswith("zh") else ""
    base_dir = os.path.abspath(os.path.join('evaluation_output', 'dacomp_da', f"{model_path}_{exp_name}{lang_suffix}"))
    os.makedirs(base_dir, exist_ok=True)

    metadata = make_metadata(
        llm_config,
        'dacomp_da',
        args.agent_cls,
        args.max_iterations,
        os.environ.get('OPENHANDS_VERSION', 'v0.53.0'),
        base_dir,
        eval_output_path_override=base_dir,
    )

    # Overwrite/skip logic
    if not args.overwrite:
        completed_ids = []
        for _, row in dataset.iterrows():
            instance_id = row['instance_id']
            result_file = os.path.join(base_dir, instance_id, 'result.json')
            if os.path.isfile(result_file):
                try:
                    with open(result_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if data.get('status') == 'success':
                        completed_ids.append(instance_id)
                except Exception:
                    pass
        if completed_ids:
            dataset = dataset[~dataset['instance_id'].isin(completed_ids)]
            logger.info(f"Skipping {len(completed_ids)} completed tasks (overwrite disabled).")
        logger.info(f"Remaining tasks after skip check: {len(dataset)}")
        if dataset.empty:
            logger.info("No DA tasks to run after applying overwrite/skip filters; exiting.")
            exit(0)

    # Set up output
    output_file = os.path.join(metadata.eval_output_dir, 'output.jsonl')

    instances = prepare_dataset_custom(
        dataset,
        output_file,
        args.num_tasks,
        eval_ids=args.task_ids,
        skip_num=args.skip_num
    )

    if instances.empty:
        logger.error("No instances to process after filtering!")
        exit(1)

    logger.info(f"Processing {len(instances)} instances")

    progress_file = os.path.join(metadata.eval_output_dir, 'progress.json')
    with open(progress_file, 'w') as f:
        json.dump({"total": len(instances), "completed": 0, "status": "running"}, f)

    try:
        workers = max(1, min(int(args.concurrency), len(instances)))
        run_evaluation(instances, metadata, output_file, workers, process_instance)

        with open(progress_file, 'w') as f:
            json.dump({"total": len(instances), "completed": len(instances), "status": "completed"}, f)

    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        with open(progress_file, 'w') as f:
            json.dump({"total": len(instances), "completed": 0, "status": "failed", "error": str(e)}, f)
        raise
