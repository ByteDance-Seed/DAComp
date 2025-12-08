import asyncio
import json
import os
import inspect
import re
import time, random
import argparse
from typing import Dict, Optional

import pandas as pd

from openhands.llm.llm_registry import LLMRegistry

from evaluation.utils.shared import (
    EvalMetadata,
    EvalOutput,
    get_default_sandbox_config_for_eval,
    make_metadata,
    reset_logger_for_multiprocessing,
    run_evaluation,
)
from openhands.controller.state.state import State
from openhands.core.config import (
    OpenHandsConfig,
    get_llm_config_arg,
)
from openhands.core.logger import openhands_logger as logger
from openhands.core.main import create_runtime, run_controller
from openhands.events.action import CmdRunAction, MessageAction
from openhands.events.observation import CmdOutputObservation
from openhands.runtime.base import Runtime
from openhands.utils.async_utils import call_async_from_sync

def _resolve_de_paths(lang: Optional[str] = None) -> str:
    """Resolve DE task data paths for the selected language."""
    local_root = os.path.join(os.path.dirname(__file__), 'data')
    lang = (lang or os.getenv("DATAAGENT_LANG", "zh")).lower()

    preferred_dirs = []
    if lang.startswith('zh'):
        preferred_dirs.extend(['dacomp_de_zh', 'dacomp_de'])
    else:
        preferred_dirs.extend(['dacomp_de', 'dacomp_de_zh'])

    for dirname in preferred_dirs:
        candidate = os.path.join(local_root, dirname)
        if os.path.isdir(candidate):
            return candidate

    # Fall back to the first candidate to surface a clear error downstream
    return os.path.join(local_root, preferred_dirs[0])

def _sanitize_exp_name(name: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', name.strip())
    return cleaned or 'default'


def _model_path_from_llm(llm_config) -> str:
    model_name = llm_config.model.split('/')[-1]
    return model_name.replace(':', '_').replace('@', '-')


def _get_output_base_dir_for_task(task_type: str, metadata: EvalMetadata) -> str:
    details = (getattr(metadata, 'details', {}) or {})
    base_dirs = details.get('output_base_dirs') or {}
    base_dir = base_dirs.get(task_type, metadata.eval_output_dir)
    return os.path.abspath(base_dir)

def make_codeact_user_response(lang: str):
    zh = (
        '只有完成任后才能使用 "finish" 工具结束此次交互。\n'
        '重要：你绝不能请求人类帮助，也不要使用互联网来解决此任务。\n'
    )
    en = (
        'When you believe the task is completed, call the "finish" tool to end the session.\n'
        'Important: Do not ask a human for help and do not use the Internet for this task.\n'
    )
    template = zh if lang == 'zh' else en

    def responder(state: State) -> str:
        return template
    return responder


def _guidelines_block(lang: str) -> str:
    if lang == 'zh':
        return (
            '重要：你只能与提供的环境交互，绝不要请求人类帮助。\n'
        )
    return (
        'Important: You can only interact with the provided environment. Do not ask a human for help.\n'
    )

AGENT_SUFFIX_BY_LANG = {
    'zh': '当你认为已完成任务时，必须使用 "finish" 工具结束此次交互。若仍需继续开发或调试代码，请不要调用 "finish"，继续完善后再一次性提交。',
    'en': 'When you believe the task is completed, you must call the "finish" tool to end the session. If you still need to develop or debug code, do not call "finish"; continue and complete everything first.',
}


def get_config(
    metadata: EvalMetadata,
    workspace_base: Optional[str] = None,
) -> OpenHandsConfig:
    """Configure the OpenHands environment for dataagent DE tasks."""
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

def check_sql_files_generated(runtime: Runtime) -> bool:
    """Check if SQL files have been generated in the sql/ directory."""
    try:
        check = runtime.run_action(CmdRunAction(
            command='find sql -name "*.sql" -type f | wc -l'
        ))
        count = int((check.content or "0").strip())
        return count > 0
    except Exception:
        return False

def execute_run_py(runtime: Runtime) -> tuple[bool, str]:
    """Try to execute run.py to validate the SQL pipeline."""
    try:
        # First check if run.py exists
        check = runtime.run_action(CmdRunAction(
            command='test -f run.py && echo "EXISTS" || echo "MISSING"'
        ))
        if "MISSING" in (check.content or ""):
            return False, "run.py file not found"

        result = runtime.run_action(CmdRunAction(
            command='timeout 300 python run.py'
        ))
        content = (result.content or "").strip()

        try:
            meta = (result.extras or {}).get("metadata") or {}
            exit_code = meta.get("exit_code", 0)
            success = exit_code == 0
        except Exception:
            success = not any(error in content.lower() for error in ['error', 'exception', 'traceback', 'failed'])

        return success, content
    except Exception as e:
        return False, f"Execution error: {str(e)}"

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

def save_de_task_results_simple(instance_id: str, metadata: EvalMetadata, runtime: Runtime, workspace_path: str, sql_generated: bool, run_success: bool, run_output: str, histories: list, summary: dict, instruction: str = "", error_message: str = None, output_base_dir: Optional[str] = None) -> None:
    """Save DE task results - simplified version since workspace files are already in place."""
    base_dir = output_base_dir or metadata.eval_output_dir
    task_output_dir = os.path.abspath(os.path.join(base_dir, instance_id))

    try:
        simplified_traj = simplify_histories(histories or [])
        if not summary:
            summary = build_summary(simplified_traj)
    except Exception as e:
        logger.warning(f"Failed to simplify trajectory: {e}")
        simplified_traj = []

    result_data = {
        "instance_id": instance_id,
        "instruction": instruction,
        "sql_files_generated": sql_generated,
        "run_py_success": run_success,
        "run_py_output": run_output,
        "summary": summary,
        "trajectory": simplified_traj,
        "status": "error" if error_message else ("success" if run_success else "incomplete"),
        "error": error_message,
    }

    result_file = os.path.join(task_output_dir, 'result.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)

    if runtime:
        try:
            sql_staging_result = runtime.run_action(CmdRunAction(command='find sql/staging -name "*.sql" -type f 2>/dev/null | wc -l'))
            sql_intermediate_result = runtime.run_action(CmdRunAction(command='find sql/intermediate -name "*.sql" -type f 2>/dev/null | wc -l'))
            sql_marts_result = runtime.run_action(CmdRunAction(command='find sql/marts -name "*.sql" -type f 2>/dev/null | wc -l'))
            sql_files_result = runtime.run_action(CmdRunAction(command='ls -la sql/ 2>/dev/null || echo "SQL directory not found"'))

            file_count_result = runtime.run_action(CmdRunAction(command='find . -type f | wc -l'))

            workspace_summary = {
                "sql_files_check": sql_files_result.content if sql_files_result else "No result",
                "sql_staging_count": sql_staging_result.content.strip() if sql_staging_result else "0",
                "sql_intermediate_count": sql_intermediate_result.content.strip() if sql_intermediate_result else "0",
                "sql_marts_count": sql_marts_result.content.strip() if sql_marts_result else "0",
                "total_files_in_workspace": file_count_result.content.strip() if file_count_result else "Unknown",
                "workspace_path": workspace_path
            }

            summary_file = os.path.join(task_output_dir, 'workspace_summary.json')
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(workspace_summary, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.warning(f"Failed to generate workspace summary for {instance_id}: {e}")

    logger.info(f"Saved DE task results to: {task_output_dir} (workspace files already in place)")


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

    # Local CLI runtime: no container cleanup needed


def is_task_complete(instance_id: str, output_base_dir: str) -> bool:
    """A task is considered complete only if result.json exists and run_py_success is True."""
    try:
        result_file = os.path.join(output_base_dir, instance_id, 'result.json')
        if not os.path.isfile(result_file):
            return False
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return bool(data.get('run_py_success'))
    except Exception as e:
        logger.warning(f"Failed to read result.json for {instance_id}: {e}")
        return False


def load_de_dataset(task_type_filter: str = 'all', lang: Optional[str] = None):
    """Load and prepare the DE dataset from dacomp_de or dacomp_de_zh directory.

    Args:
        task_type_filter: Filter by task type ('impl', 'evol', or 'all').
        lang: Dataset language hint ('zh' -> dacomp_de_zh, otherwise dacomp_de).
    """
    de_data_path = _resolve_de_paths(lang)
    if not os.path.exists(de_data_path):
        logger.error(f"DE data directory not found: {de_data_path}")
        raise FileNotFoundError(f"DE data directory not found: {de_data_path}")

    normalized_task_type = task_type_filter

    # Get all DE task directories
    tasks = []
    for task_dir in sorted(os.listdir(de_data_path)):
        task_path = os.path.join(de_data_path, task_dir)
        if not os.path.isdir(task_path):
            continue

        is_impl = task_dir.startswith('dacomp-de-impl-')
        is_evol = task_dir.startswith('dacomp-de-evol-')

        if not (is_impl or is_evol):
            continue

        # Check for required files
        config_path = os.path.join(task_path, 'config', 'layer_dependencies.yaml')
        run_py_path = os.path.join(task_path, 'run.py')
        question_path = os.path.join(task_path, 'question.md')
        data_contract_path = os.path.join(task_path, 'docs', 'data_contract.yaml')

        # Determine task type
        task_type = 'impl' if is_impl else 'evol'

        # Skip tasks based on filter
        if normalized_task_type != 'all' and task_type != normalized_task_type:
            continue

        # For impl tasks, check basic required files
        # For evol tasks, also check for question.md
        required_files = [config_path, run_py_path]
        if task_type == 'impl':
            required_files.append(data_contract_path)
        else:
            required_files.append(question_path)

        if all(os.path.exists(p) for p in required_files):
            tasks.append({
                'id': task_dir,
                'type': 'Data Engineering',
                'task_type': task_type,
                'instruction': '', # Will be set later
                'hardness': 'Hard',
                'post_process': []
            })
            logger.info(f"Found DE {task_type} task: {task_dir}")
        else:
            logger.warning(f"Skipping incomplete DE task: {task_dir}")

    logger.info(f"Loaded {len(tasks)} DE tasks from {de_data_path}")

    # Create dataset
    dataset = pd.DataFrame(tasks)
    dataset['source_dir'] = dataset['id'].apply(lambda x: os.path.join(de_data_path, x))
    dataset['instance_id'] = dataset['id']

    return dataset

def get_task_files(task_dir: str) -> Dict[str, str]:
    """Get all files in a task directory with their contents."""
    files = {}
    if not os.path.exists(task_dir):
        logger.warning(f"Task directory does not exist: {task_dir}")
        return files

    for root, _, filenames in os.walk(task_dir):
        for filename in filenames:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, task_dir)

            # Skip if not a regular file
            if not os.path.isfile(filepath):
                logger.warning(f"Skipping non-file: {rel_path}")
                continue

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                files[rel_path] = content
            except UnicodeDecodeError:
                # Binary file, just note its existence
                files[rel_path] = "[BINARY FILE]"
            except IsADirectoryError:
                logger.warning(f"Skipping directory that was listed as file: {rel_path}")
                continue
            except Exception as e:
                logger.warning(f"Error reading file {rel_path}: {e}")
                files[rel_path] = f"[ERROR READING FILE: {e}]"
    return files

def create_de_task_prompt(instance: pd.Series, lang: str) -> str:
    """Create a prompt for the DE task."""

    task_type = instance.get('task_type', 'impl')

    # Base instruction for DE tasks - implementation vs evolution
    if task_type == 'impl':
        if lang == 'zh':
            base_instruction = '''你是一名专业的数据工程师，负责根据数据契约文档实现完整的SQL数据管道。
## 目标
根据 `docs/data_contract.yaml` 和 `config/layer_dependencies.yaml` 中的规范，填充 `./sql/` 目录中的 SQL 文件。你的任务很明确：编写必要的 SQL 代码，确保 `run.py` 可以成功执行。

一定要查看`docs/data_contract.yaml` 这个文件的内容，要仔细一些，可以使用工具查看,这个文件的内容很长，你可以分块去查看，你的任务就是根据这个文件的内容，去完成sql文件的编写。

## 项目背景
* 原始数据已加载到 `xxxx_start.duckdb`（注意‘xxxx’是项目名称占位符，如 `greenhouse_start.duckdb` 或 `google_ads_start.duckdb`，下文中出现‘xxxx’，也是这个意思）。
* 当前运行 `python run.py` 可以完成数据转换，输出为 `xxxx.duckdb`。
* 现有 SQL 工程存放在 `sql/` 文件夹中。
* `docs/data_contract.yaml` 中放置了当前的需求文档。

**实现要求：**
1. **严格遵守配置**：
    * 所有 SQL 逻辑和依赖必须严格按照 YAML 配置文件中定义的 `staging`、`intermediate` 和 `marts` 层级结构编写。

2. **文件和目录结构**：
    * 必须在相应的层级子目录中创建 SQL 文件（例如：`sql/staging/`、`sql/intermediate/`、`sql/marts/`）。
    * 严格遵循预定义的文件命名约定和编码风格。

3. **使用纯 DuckDB 语法**：
    * 所有 SQL 代码必须兼容 DuckDB。
    * **请勿**在文件末尾用分号 (`;`) 结束 SQL 语句。

4. **禁止 dbt 语法**：
    * 必须使用 `schema.table_name` 格式直接引用上游表。
    * **不要**使用 dbt 的 `ref()` 函数。

    **示例**：
    * **正确 ✅**：
```sql
    with account_base as (
    select *
    from staging.stg_salesforce__account
    where not is_deleted
    ),

    account_enriched as (
    select
    account_id,
    ...
```
    * **错误 ❌**：
```sql
    WITH accounts AS (
    SELECT *
    FROM {{{{ ref('stg_salesforce__account') }}}}
    ),
    contacts AS (
    SELECT *
    FROM {{{{ ref('stg_salesforce__contact') }}}}
    ),
    ...
```

**输出标准：**
确保生成的SQL文件能够通过 `run.py` 成功执行，产出符合业务需求的高质量数据结果。'''
        else:
            base_instruction = '''You are a professional Data Engineer responsible for implementing a complete SQL data pipeline based on data contract documents.

## Objectives
Populate the SQL files in the `./sql/` directory according to the specifications in `docs/data_contract.yaml` and `config/layer_dependencies.yaml`. Your task is clear: write the necessary SQL code to ensure `run.py` executes successfully.

You MUST carefully review the content of `docs/data_contract.yaml`. You may use tools to view it. Since the file content is long, you can view it in chunks. Your task is to complete the SQL file writing based on the content of this file.

## Project Background
* Raw data has been loaded into `xxxx_start.duckdb` (Note: 'xxxx' is a placeholder for the project name, such as `greenhouse_start.duckdb` or `google_ads_start.duckdb`; 'xxxx' appearing below carries the same meaning).
* Currently, running `python run.py` completes the data transformation and outputs `xxxx.duckdb`.
* The existing SQL project is stored in the `sql/` folder.
* The current requirements documentation is located in `docs/data_contract.yaml`.

**Implementation Requirements:**
1. **Strictly Adhere to Configuration**:
    * All SQL logic and dependencies must be written strictly according to the `staging`, `intermediate`, and `marts` hierarchy defined in the YAML configuration files.

2. **File and Directory Structure**:
    * SQL files must be created in the corresponding level subdirectories (e.g., `sql/staging/`, `sql/intermediate/`, `sql/marts/`).
    * Strictly follow predefined file naming conventions and coding styles.

3. **Use Pure DuckDB Syntax**:
    * All SQL code must be compatible with DuckDB.
    * **Do NOT** end SQL statements with a semicolon (`;`) at the end of the file.

4. **No dbt Syntax**:
    * You must reference upstream tables directly using the `schema.table_name` format.
    * **Do NOT** use the dbt `ref()` function.

    **Examples**:
    * **Correct ✅**:
```sql
    with account_base as (
    select *
    from staging.stg_salesforce__account
    where not is_deleted
    ),

    account_enriched as (
    select
    account_id,
    ...
```

* **Incorrect ❌**:
```sql
    WITH accounts AS (
    SELECT *
    FROM {{{{ ref('stg_salesforce__account') }}}}
    ),
    contacts AS (
    SELECT *
    FROM {{{{ ref('stg_salesforce__contact') }}}}
    ),
    ...
```
Output Standard: Ensure the generated SQL files can be successfully executed by run.py to produce high-quality data results that meet business requirements.
'''
    elif task_type == 'evol':
        if lang == 'zh':
            base_instruction = '''你是一名专业的数据工程师，负责根据业务需求对现有的SQL数据管道进行演进和改进。

**核心任务：**
根据 `./question.md` 文件中的具体业务需求，对现有的SQL数据管道进行修改和优化。

## 项目背景
* 原始数据已加载到 `xxxx_start.duckdb`（注意‘xxxx’是项目名称占位符，如 `greenhouse_start.duckdb` 或 `google_ads_start.duckdb`，下文中出现‘xxxx’，也是这个意思）。
* 当前运行 `python run.py` 可以完成数据转换，输出为 `xxxx.duckdb`。
* 现有 SQL 工程存放在 `./sql/` 文件夹中。

**实现要求：**
1. **需求理解** - 仔细分析question.md中的业务需求和技术规范
2. 在修改或新增文件前，请先探测现有项目的 schema 和依赖关系，避免引用不存在的字段或表。
3. 新增或修改对应的 SQL 文件（路径需符合项目规范，如 `sql/staging/...`, `sql/intermediate/...`, `sql/marts/...`）。
4. **测试验证** - 确保修改后的代码能正常运行

**完成标准：**
确保修改后的SQL文件能够通过 `run.py` 成功执行（禁止修改 run.py 文件), 满足question.md中提出的业务需求。'''
        else:
            base_instruction = '''You are a professional Data Engineer responsible for evolving and improving an existing SQL data pipeline based on business requirements.

**Core Task:**
Modify and optimize the existing SQL data pipeline according to the specific business requirements in the `./question.md` file.

## Project Background
* Raw data has been loaded into `xxxx_start.duckdb` (Note: 'xxxx' is a placeholder for the project name, such as `greenhouse_start.duckdb` or `google_ads_start.duckdb`; 'xxxx' appearing below carries the same meaning).
* Currently, running `python run.py` completes the data transformation and outputs `xxxx.duckdb`.
* The existing SQL project is stored in the `./sql/` folder.

**Implementation Requirements:**
1. **Requirement Understanding** - Carefully analyze the business requirements and technical specifications in `question.md`.
2. Before modifying or adding files, please inspect the schema and dependencies of the existing project to avoid referencing non-existent fields or tables.
3. Add or modify the corresponding SQL files (paths must conform to project standards, e.g., `sql/staging/...`, `sql/intermediate/...`, `sql/marts/...`).
4. **Testing and Verification** - Ensure that the modified code runs correctly.

**Completion Standard:**
Ensure the modified SQL files can be successfully executed by `run.py` (modifying the `run.py` file is prohibited) and meet the business requirements proposed in `question.md`.'''
    else:
        base_instruction = ''

    prompt = ""

    task_files = get_task_files(instance['source_dir'])

    # Add specific question content for evol tasks
    if task_type == 'evol' and 'question.md' in task_files:
        question_content = task_files['question.md']
        if question_content != "[BINARY FILE]":
            if lang == 'zh':
                prompt += f"## 具体业务需求 (来自 question.md)：\n\n{question_content}\n\n"
            else:
                prompt += f"## Specific Business Requirements (from question.md):\n\n{question_content}\n\n"

    if lang == 'zh':
        prompt += f"## 任务说明：\n{base_instruction}\n\n"
    else:
        prompt += f"## Task Description:\n{base_instruction}\n\n"

    # Include contract file relative paths for impl tasks to guide the agent
    if task_type == 'impl':
        # Collect YAML contract files under docs/
        contract_yaml_paths = sorted([f"./{p}" for p in task_files.keys() if p.startswith('docs/') and p.endswith('.yaml')])
        if contract_yaml_paths:
            if lang == 'zh':
                prompt += "## 契约文件路径提示：\n" + "\n".join(f"- {p}" for p in contract_yaml_paths) + "\n\n"
            else:
                prompt += "## Contract file paths:\n" + "\n".join(f"- {p}" for p in contract_yaml_paths) + "\n\n"

    # # For de-impl tasks, include the data_contract.yaml and layer_dependencies.yaml content in the prompt
    if task_type == 'impl':
        # Include data_contract.yaml
        if 'docs/data_contract.yaml' in task_files:
            data_contract_content = task_files['docs/data_contract.yaml']
            if data_contract_content != "[BINARY FILE]" and data_contract_content.strip():
                if lang == 'zh':
                    prompt += f"## 数据契约文档 (docs/data_contract.yaml)：\n\n```yaml\n{data_contract_content}\n```\n\n"
                else:
                    prompt += f"## Data Contract Documentation (docs/data_contract.yaml):\n\n```yaml\n{data_contract_content}\n```\n\n"
    return prompt

def prepare_workspace(
    instance: pd.Series,
    task_output_dir: str,
) -> str:
    """Prepare workspace by copying task files to output directory."""
    import shutil

    logger.info(f'{"=" * 50} BEGIN Workspace Preparation {"=" * 50}')

    task_dir = instance['source_dir']
    if not os.path.exists(task_dir):
        logger.error(f"Source directory does not exist: {task_dir}")
        raise FileNotFoundError(f"Source directory does not exist: {task_dir}")

    logger.info(f"Copying task files from {task_dir} to {task_output_dir}")

    task_output_dir = os.path.abspath(task_output_dir)
    os.makedirs(task_output_dir, exist_ok=True)

    for item in os.listdir(task_dir):
        src_path = os.path.join(task_dir, item)
        dst_path = os.path.join(task_output_dir, item)

        try:
            if os.path.isdir(src_path):
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                shutil.copytree(src_path, dst_path)
                logger.info(f"Copied directory: {item}")
            else:
                shutil.copy2(src_path, dst_path)
                logger.info(f"Copied file: {item}")
        except Exception as e:
            logger.warning(f"Failed to copy {item}: {e}")

    sql_dir = os.path.join(task_output_dir, 'sql')
    os.makedirs(sql_dir, exist_ok=True)
    logger.info(f"Ensured sql directory exists: {sql_dir}")

    logger.info(f"Files in workspace: {os.listdir(task_output_dir)}")

    logger.info(f'{"=" * 50} END Workspace Preparation {"=" * 50}')
    return task_output_dir


def initialize_runtime(
    runtime: Runtime,
    instance: pd.Series,
):
    """Initialize the runtime environment for the DE task."""
    logger.info(f'{"-" * 50} BEGIN Runtime Initialization Fn {"-" * 50}')
    obs: CmdOutputObservation

    obs = runtime.run_action(CmdRunAction(command='ls -la .'))
    logger.info(f"Workspace contents (mounted): {obs.content}")

    logger.info(f'{"-" * 50} END Runtime Initialization Fn {"-" * 50}')

def process_instance(
    instance: pd.Series,
    metadata: EvalMetadata,
    reset_logger: bool = True,
) -> EvalOutput:
    """Process a single DE task instance."""
    try:
        stagger = float(os.getenv("DATAAGENT_STAGGER_SEC", "2"))
        if stagger > 0:
            time.sleep(random.random() * stagger)
    except Exception:
        pass

    lang = os.getenv("DATAAGENT_LANG", "zh").lower()
    prompt_lang = os.getenv("DATAAGENT_PROMPT_LANG", lang).lower()
    instance_id = instance['id']
    task_type = instance.get('task_type', 'impl')
    output_base_dir = _get_output_base_dir_for_task(task_type, metadata)

    if reset_logger:
        log_dir = os.path.join(output_base_dir, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        reset_logger_for_multiprocessing(logger, instance_id, log_dir)
    else:
        logger.info(f'Starting execution for instance {instance_id}.')

    logger.info(f'Starting execution for instance {instance_id}')
    runtime: Runtime | None = None

    try:
        task_output_dir = os.path.abspath(os.path.join(output_base_dir, instance_id))
        workspace_path = prepare_workspace(instance, task_output_dir)

        workspace_path = os.path.abspath(workspace_path)
        logger.info(f"Using absolute workspace path: {workspace_path}")

        config = get_config(metadata, workspace_path)

        instruction = create_de_task_prompt(instance, prompt_lang)
        instruction += _guidelines_block(prompt_lang)
        instruction += "\n\n" + AGENT_SUFFIX_BY_LANG.get(prompt_lang, AGENT_SUFFIX_BY_LANG['zh'])

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
                fake_user_response_fn=make_codeact_user_response(prompt_lang),
                runtime=runtime,
            )
        )

        # Process the results
        from evaluation.utils.shared import compatibility_for_eval_history_pairs
        histories = compatibility_for_eval_history_pairs(state.history) if state else []
        simplified_trajectory = simplify_histories(histories)
        summary = build_summary(simplified_trajectory)

        # Check if SQL files were generated
        sql_generated = check_sql_files_generated(runtime)

        # Try to execute run.py
        run_success, run_output = execute_run_py(runtime)

        logger.info(f"Task {instance_id} completed. SQL generated: {sql_generated}, Run success: {run_success}")

        # Determine if task completed successfully
        test_result = {
            'sql_files_generated': sql_generated,
            'run_py_success': run_success,
            'run_py_output': run_output,
            'summary': summary
        }

        # Save simplified results (workspace files are already in place)
        save_de_task_results_simple(
            instance_id,
            metadata,
            runtime,
            workspace_path,
            sql_generated,
            run_success,
            run_output,
            histories,
            summary,
            instruction=instruction,
            output_base_dir=output_base_dir
        )

        return EvalOutput(
            instance_id=instance_id,
            instruction=instruction,
            test_result=test_result,
            metadata=metadata,
            history=histories,
            metrics={
                'sql_generated': sql_generated,
                'run_success': run_success,
                'total_steps': summary.get('total_steps', 0),
                'tool_calls': summary.get('tool_calls', 0)
            },
            error=None
        )

    except Exception as e:
        logger.error(f"Error processing instance {instance_id}: {e}")

        # Try to save whatever progress was made even if there was an error
        try:
            safe_histories = locals().get('histories', [])
            safe_summary = locals().get('summary', {})
            safe_sql_generated = False
            safe_run_success = False
            safe_run_output = str(e)
            safe_workspace_path = locals().get('workspace_path', '')

            if runtime:
                try:
                    safe_sql_generated = check_sql_files_generated(runtime)
                    _, safe_run_output = execute_run_py(runtime)
                except Exception:
                    pass

            save_de_task_results_simple(
                instance_id,
                metadata,
                runtime,
                safe_workspace_path,
                safe_sql_generated,
                safe_run_success,
                safe_run_output,
                safe_histories,
                safe_summary,
                instruction=locals().get('instruction', ''),
                error_message=str(e),
                output_base_dir=output_base_dir
            )
        except Exception as save_error:
            logger.warning(f"Failed to save partial results: {save_error}")

        return EvalOutput(
            instance_id=instance_id,
            instruction=f"DE Task: {instance_id}",
            test_result={'result': {'status': 'error', 'message': str(e)}},
            metadata=metadata,
            history=[],
            metrics={'sql_generated': False, 'run_success': False},
            error=str(e)
        )

    finally:
        try:
            cleanup_runtime_container(runtime)
        except Exception as e:
            logger.warning(f"Post-task per-runtime cleanup failed: {e}")


def prepare_dataset_custom(
    dataset: pd.DataFrame,
    output_file: str,
    eval_n_limit: int,
    eval_ids: Optional[list[str]] = None,
    skip_num: Optional[int] = None,
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
        for k, v in instance_dict.items():
            if isinstance(v, pd.Timestamp):
                instance_dict[k] = str(v)
            elif isinstance(v, dict):
                instance_dict[k] = make_serializable(v)
        return instance_dict

    new_dataset = [
        make_serializable(row.to_dict()) for _, row in dataset.iterrows()
    ]

    logger.info(f'Total instances to process: {len(new_dataset)}')
    return pd.DataFrame(new_dataset)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run DATAAGENT DE task execution")
    parser.add_argument('-c', '--agent-cls', type=str, default='CodeActAgent', help='Agent class to use')
    parser.add_argument('-l', '--llm-config', type=str, required=True, help='LLM configuration')
    parser.add_argument('-i', '--max-iterations', type=int, default=30, help='Maximum iterations')
    parser.add_argument('-n', '--num-tasks', type=int, default=1, help='Number of tasks to process')
    parser.add_argument('--task-ids', type=str, help='Specific task IDs to process (comma-separated)')
    parser.add_argument('--skip-num', type=int, default=0, help='Number of tasks to skip from beginning')
    parser.add_argument('-j', '--concurrency', type=int, default=1, help='Number of parallel workers to run tasks')
    parser.add_argument('--lang', choices=['zh','en'], default='zh', help='Dataset language and source dir (zh uses dacomp_de_zh; en uses dacomp_de)')
    parser.add_argument('--prompt-lang', choices=['zh','en'], default=None, help='Prompt language (system prompt and guidance). Default: same as --lang')
    parser.add_argument('--task-type', choices=['impl','evol','all'], default='all', help='Filter tasks by type: impl (implementation), evol, or all (default: all)')
    parser.add_argument('--exp-name', type=str, default='default', help='Custom experiment name used in output directory naming')
    parser.add_argument('--overwrite', action='store_true', help='Re-run tasks even if a successful result already exists')
    args = parser.parse_args()

    # Set language from arguments or environment
    lang = args.lang or os.getenv("DATAAGENT_LANG", "zh")
    prompt_lang = args.prompt_lang or args.lang or os.getenv("DATAAGENT_PROMPT_LANG", lang)

    task_type_env = {
        'impl': 'de-impl',
        'evol': 'de-evol',
    }.get(args.task_type, 'de')

    # Set environment variables for consistency
    os.environ["DATAAGENT_LANG"] = lang
    os.environ["DATAAGENT_PROMPT_LANG"] = prompt_lang
    os.environ["DATAAGENT_TASK_TYPE"] = task_type_env

    logger.info("Starting DATAAGENT DE evaluation with parameters:")
    logger.info(f"  Agent: {args.agent_cls}")
    logger.info(f"  LLM Config: {args.llm_config}")
    logger.info(f"  Max Iterations: {args.max_iterations}")
    logger.info(f"  Number of Tasks: {args.num_tasks}")
    logger.info(f"  Skip Number: {args.skip_num}")
    logger.info(f"  Concurrency: {args.concurrency}")
    logger.info(f"  Lang (dataset/source): {lang}")
    logger.info(f"  Prompt Lang: {prompt_lang}")
    logger.info(f"  Task Type Filter: {args.task_type}")
    logger.info(f"  DataAgent Task Type (env): {task_type_env}")
    if args.task_ids:
        logger.info(f"  Task IDs: {args.task_ids}")

    # Load DE dataset
    dataset = load_de_dataset(args.task_type, lang)

    if dataset.empty:
        logger.error("No DE tasks found in dataset!")
        exit(1)

    # Set up LLM config
    llm_config = get_llm_config_arg(args.llm_config)
    if llm_config is None:
        raise ValueError(f'Could not find LLM config: --llm_config {args.llm_config}')

    exp_name = _sanitize_exp_name(args.exp_name or "default")
    model_path = _model_path_from_llm(llm_config)
    lang_suffix = "_zh" if str(lang).lower().startswith("zh") else ""

    output_base_dirs = {
        'impl': os.path.abspath(os.path.join('evaluation_output', 'dacomp_de_impl', f"{model_path}_{exp_name}{lang_suffix}")),
        'evol': os.path.abspath(os.path.join('evaluation_output', 'dacomp_de_evol', f"{model_path}_{exp_name}{lang_suffix}")),
    }
    if args.task_ids:
        eval_ids = [id.strip() for id in args.task_ids.split(',') if id.strip()]
    else:
        eval_ids = None

    # Create metadata with custom output roots per task type
    metadata_details = {
        'output_base_dirs': output_base_dirs,
        'exp_name': exp_name,
    }

    def run_for_subset(subset: pd.DataFrame, subtype: str):
        """Run evaluation for a specific task subtype (impl/evol)."""
        if subset.empty:
            logger.info(f"No tasks to process for subtype={subtype}")
            return

        base_dir = output_base_dirs.get(subtype, output_base_dirs['impl'])
        os.makedirs(base_dir, exist_ok=True)

        metadata = make_metadata(
            llm_config,
            f"dacomp_de_{subtype}",
            args.agent_cls,
            args.max_iterations,
            os.environ.get('OPENHANDS_VERSION', 'v0.53.0'),
            base_dir,
            details=metadata_details,
            eval_output_path_override=base_dir,
        )

        if not args.overwrite:
            completed_ids = []
            for _, row in subset.iterrows():
                instance_id = row['instance_id']
                if is_task_complete(instance_id, base_dir):
                    completed_ids.append(instance_id)
            if completed_ids:
                subset = subset[~subset['instance_id'].isin(completed_ids)]
                logger.info(f"Skipping {len(completed_ids)} completed tasks for subtype={subtype} (overwrite disabled).")
            logger.info(f"Remaining tasks after skip check (subtype={subtype}): {len(subset)}")
            if subset.empty:
                logger.info(f"No DE tasks to run after applying overwrite/skip filters for subtype={subtype}; skipping.")
                return

        output_file = os.path.join(base_dir, 'output.jsonl')

        instances = prepare_dataset_custom(
            subset,
            output_file,
            args.num_tasks,
            eval_ids,
            args.skip_num,
        )

        if instances.empty:
            logger.error(f"No instances to process after filtering for subtype={subtype}!")
            return

        logger.info(f"Processing {len(instances)} instances (subtype={subtype})")

        progress_file = os.path.join(base_dir, 'progress.json')
        with open(progress_file, 'w') as f:
            json.dump({"total": len(instances), "completed": 0, "status": "running"}, f)

        try:
            workers = max(1, min(int(args.concurrency), len(instances)))
            run_evaluation(instances, metadata, output_file, workers, process_instance)

            with open(progress_file, 'w') as f:
                json.dump({"total": len(instances), "completed": len(instances), "status": "completed"}, f)

        except Exception as e:
            logger.error(f"Evaluation failed for subtype={subtype}: {e}")
            with open(progress_file, 'w') as f:
                json.dump({"total": len(instances), "completed": 0, "status": "failed", "error": str(e)}, f)
            raise

    if args.task_type == 'all':
        run_for_subset(dataset[dataset['task_type'] == 'impl'], 'impl')
        run_for_subset(dataset[dataset['task_type'] == 'evol'], 'evol')
    else:
        run_for_subset(dataset, args.task_type)
