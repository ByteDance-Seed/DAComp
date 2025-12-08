import os
import json
import asyncio
import argparse
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Reuse utilities from the base script to avoid duplication
from run_infer_de import (
    make_codeact_user_response,
    _guidelines_block,
    AGENT_SUFFIX_BY_LANG,
    get_config,
    execute_run_py,
    simplify_histories,
    build_summary,
    save_de_task_results_simple,
    cleanup_runtime_container,
    prepare_workspace,
    initialize_runtime,
    load_de_dataset,
    prepare_dataset_custom,
)

from openhands.llm.llm_registry import LLMRegistry
from openhands.core.config import OpenHandsConfig, get_llm_config_arg
from openhands.core.logger import openhands_logger as logger
from openhands.core.main import create_runtime, run_controller
from openhands.events.action import MessageAction, CmdRunAction
from openhands.controller.state.state import State
from openhands.utils.async_utils import call_async_from_sync

# ============ Config helpers ============

def _try_load_yaml_or_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    # Try YAML first
    try:
        import yaml  # type: ignore
        return yaml.safe_load(raw) or {}
    except Exception:
        pass
    # Fallback JSON
    try:
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"Failed to parse agents config as YAML or JSON: {e}")


def load_agents_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Agents config not found: {path}")
    cfg = _try_load_yaml_or_json(path)
    # Minimal defaults
    cfg.setdefault("version", 1)
    cfg.setdefault("runtime", {}).setdefault("shared", True)
    cfg.setdefault("validation", {}).setdefault("run_per_item", True)
    cfg.setdefault("validation", {}).setdefault("retries", 5)
    cfg.setdefault("validation", {}).setdefault("run_per_layer", False)
    cfg.setdefault("prompt", {}).setdefault("lang", os.getenv("DATAAGENT_PROMPT_LANG", os.getenv("DATAAGENT_LANG", "zh")))
    if "agents" not in cfg or not isinstance(cfg["agents"], list) or len(cfg["agents"]) == 0:
        # Provide a single default logical agent if not configured
        cfg["agents"] = [{"id": "A1"}]
    return cfg


def load_build_plan_for_instance(instance: pd.Series, fallback_config_path: Optional[str] = None) -> dict:
    """Load per-project build_plan.yaml for the given instance.

    If fallback_config_path is provided and not 'auto', try that path first.
    Otherwise use '<source_dir>/build_plan.yaml'. If neither exists, fall back to
    '<source_dir>/agents.yaml' if present; otherwise raise FileNotFoundError.
    """
    fb = (fallback_config_path or '').strip()
    if fb and fb.lower() != 'auto' and os.path.exists(fb):
        return load_agents_config(fb)

    src_dir = instance.get("source_dir") or instance.get("src_dir") or instance.get("project_dir")
    if not src_dir:
        raise FileNotFoundError("Instance missing source_dir; cannot locate build_plan.yaml")
    plan_path = os.path.join(src_dir, "build_plan.yaml")
    if os.path.exists(plan_path):
        return load_agents_config(plan_path)
    legacy_agents = os.path.join(src_dir, "agents.yaml")
    if os.path.exists(legacy_agents):
        return load_agents_config(legacy_agents)
    raise FileNotFoundError(f"build_plan.yaml not found for project: {plan_path}")


def _sanitize_exp_name(name: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', name.strip())
    return cleaned or 'default'


def _model_path_from_llm(llm_config) -> str:
    model_name = llm_config.model.split('/')[-1]
    return model_name.replace(':', '_').replace('@', '-')


def is_task_complete(instance_id: str, output_base_dir: str) -> bool:
    """A task is complete iff result.json exists and run_py_success is True."""
    try:
        result_file = os.path.join(output_base_dir, instance_id, 'result.json')
        if not os.path.isfile(result_file):
            return False
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return bool(data.get('run_py_success'))
    except Exception:
        return False


# ============ Inventory (docs/*.yaml) ============

def _detect_layer_from_path(rel_path: str) -> str:
    lp = rel_path.lower()
    if "/staging/" in lp or rel_path.endswith("staging.yaml") or "staging_" in os.path.basename(lp):
        return "staging"
    if "/intermediate" in lp or "intermediate" in os.path.basename(lp):
        return "intermediate"
    if "/marts" in lp or "marts" in os.path.basename(lp):
        return "marts"
    return "other"


def list_yaml_inventory(task_dir: str, max_embed: int = 65536) -> List[dict]:
    docs_dir = os.path.join(task_dir, "docs")
    items: List[dict] = []
    if not os.path.isdir(docs_dir):
        logger.warning(f"docs directory not found: {docs_dir}")
        return items

    # Collect all yaml files
    collected: List[Tuple[str, str]] = []  # (rel_path, layer)
    for root, _, files in os.walk(docs_dir):
        for fn in files:
            if fn.lower().endswith((".yaml", ".yml")):
                rel = os.path.relpath(os.path.join(root, fn), task_dir)
                collected.append((rel, _detect_layer_from_path(rel)))

    # Sort by (layer_order, rel_path)
    layer_order = {"staging": 0, "intermediate": 1, "marts": 2, "other": 3}
    collected.sort(key=lambda t: (layer_order.get(t[1], 9), t[0]))

    # Build items with content
    for i, (rel, layer) in enumerate(collected, start=1):
        abspath = os.path.join(task_dir, rel)
        try:
            content = open(abspath, "r", encoding="utf-8").read()
        except Exception as e:
            logger.warning(f"Failed to read {rel}: {e}")
            content = f"[ERROR READING FILE: {e}]"
        # Truncate if too large
        if isinstance(content, str) and len(content.encode("utf-8")) > max_embed:
            # Keep first and last chunk to preserve context ends
            head = content[: max_embed // 2]
            tail = content[-max_embed // 4 :]
            content = (
                f"# NOTE: Content truncated to {max_embed} bytes for prompt size.\n"
                f"# You can open the file directly in the workspace: ./{rel}\n\n"
                + head
                + "\n\n# ... (truncated) ...\n\n"
                + tail
            )
        items.append({"idx": i, "layer": layer, "path": rel, "content": content})

    return items


# ============ Assignment ============

def _parse_indices_spec(spec) -> List[int]:
    result: List[int] = []
    if spec is None:
        return result
    if isinstance(spec, int):
        return [spec]
    if isinstance(spec, list):
        for x in spec:
            if isinstance(x, int):
                result.append(x)
            elif isinstance(x, str):
                x = x.strip()
                if "-" in x:
                    a, b = x.split("-", 1)
                    try:
                        a, b = int(a.strip()), int(b.strip())
                        if a <= b:
                            result.extend(list(range(a, b + 1)))
                    except Exception:
                        pass
                else:
                    try:
                        result.append(int(x))
                    except Exception:
                        pass
    elif isinstance(spec, str):
        return _parse_indices_spec([spec])
    return sorted(set(result))


def assign_yaml_items(inventory: List[dict], cfg: dict) -> Dict[int, str]:
    """
    Assign YAML items to agents.

    Supports:
    - indices: exact indices or ranges (e.g., [1, "2-5"]). Applied first.
    - filters: layer-based assignment. Optional sharding:
      - shard: 1-based shard index for this agent
      - shards: total number of shards to split the layer into
      - strategy: "contiguous" (default) or "round_robin"

    Examples in agents.yaml:
      - id: A_staging
        assign:
          filters:
            - layer: staging
      - id: A_inter_1
        assign:
          filters:
            - layer: intermediate
              shard: 1
              shards: 4
              strategy: contiguous
    """
    assignment: Dict[int, str] = {}
    remaining = {item["idx"] for item in inventory}

    # Precompute items by layer, sorted by idx
    items_by_layer: Dict[str, List[dict]] = {}
    for item in inventory:
        items_by_layer.setdefault(item.get("layer", "other"), []).append(item)
    for layer in items_by_layer:
        items_by_layer[layer].sort(key=lambda it: it["idx"])  # ensure stable order

    agents = cfg.get("agents", [])

    # First pass: indices-based assignment in order
    for agent in agents:
        aid = agent.get("id") or f"agent_{len(assignment)}"
        indices = _parse_indices_spec(agent.get("assign", {}).get("indices"))
        for idx in indices:
            if idx in remaining:
                assignment[idx] = aid
                remaining.remove(idx)

    # Second pass: filter-based (e.g., by layer) with optional sharding
    for agent in agents:
        aid = agent.get("id") or "agent"
        filters = agent.get("assign", {}).get("filters", []) or []
        for f in filters:
            layer = f.get("layer")
            if not layer:
                continue
            candidates = [it for it in items_by_layer.get(layer, []) if it["idx"] in remaining]
            n = len(candidates)
            if n == 0:
                continue

            shard = f.get("shard")
            shards = f.get("shards")
            strategy = (f.get("strategy") or "contiguous").lower()

            selected: List[dict] = []
            if isinstance(shard, int) and isinstance(shards, int) and shards > 0 and 1 <= shard <= shards:
                if strategy == "round_robin":
                    selected = [candidates[i] for i in range(n) if (i % shards) == (shard - 1)]
                else:  # contiguous (default)
                    size = (n + shards - 1) // shards  # ceil chunk size
                    start = (shard - 1) * size
                    end = min(start + size, n)
                    selected = candidates[start:end]
            else:
                # No sharding specified: assign all remaining of this layer to this agent
                selected = candidates

            for it in selected:
                idx = it["idx"]
                if idx in remaining:
                    assignment[idx] = aid
                    remaining.remove(idx)

            # Update candidates cache for this layer
            items_by_layer[layer] = [it for it in items_by_layer[layer] if it["idx"] in remaining]

    # Fallback: any unassigned to first agent
    if remaining and len(agents) > 0:
        fallback = agents[0].get("id", "A1")
        for idx in list(remaining):
            assignment[idx] = fallback
            remaining.remove(idx)

    return assignment


# ============ Prompt building & execution ============

def build_yaml_item_prompt(item: dict, all_paths: List[str], lang: str, existing_sql_paths: Optional[List[str]] = None, forbid_run: bool = False) -> str:
    path = item.get("path", "")
    layer = item.get("layer", "other")
    content = item.get("content", "")

    header = []

    # Base instruction blocks for impl tasks (zh/en)
    base_instruction_zh = '''你是一名专业的数据工程师，负责根据数据契约文档实现完整的 SQL 数据管道。
## 目标

根据项目中的 `docs/` 下各类 YAML 数据契约文件（如 `staging_contract.yaml` 等）以及 `config/layer_dependencies.yaml` 的规范，生成完整的 SQL 管道文件，使 `run.py` 能成功执行并产出预期结果。

## 项目背景

* 原始数据已加载到 `xxxx_start.duckdb`（其中“xxxx”为项目名称，如 `greenhouse_start.duckdb`、`google_ads_start.duckdb` 等）。
* `docs/staging_contract.yaml` 定义了 **staging 层**的表结构、字段清洗和质量校验逻辑。
* `docs/<层级>/*.yaml`（如 `docs/intermediate_models/*.yaml`、`docs/marts_models/*.yaml`）定义了各层的数据模型，包括业务逻辑、字段说明和依赖关系。
* `xxxx_start.yaml` 包含原始数据的 schema 信息。
* `config/layer_dependencies.yaml` 定义了层间依赖顺序。

## 实现要求

### 1. 严格遵守契约配置

* 按 `staging_contract.yaml` 实现 **staging 层** SQL；
* 按各 `docs/<层级>/*.yaml` 实现 **intermediate**、**marts** 等层；
* 按 `config/layer_dependencies.yaml` 维护模型间依赖顺序；
* 所有表名、字段、业务逻辑、粒度定义必须与 YAML 完全一致。

### 2. 文件与目录结构

* SQL 代码按层级放置：
  如：
  ```
  sql/staging/<table_name>.sql
  sql/intermediate/<model_name>.sql
  sql/marts/<model_name>.sql
  ```
* 文件名与 YAML 中的 `name` 保持一致；
* 代码风格统一，遵守缩进与 CTE 命名规范。

### 3. SQL 编写规范（DuckDB）

* 使用 **纯 DuckDB 语法**；
* **请勿**在文件末尾用分号 (`;`) 结束 SQL 语句。
* **禁止 dbt 语法**，不得使用 `ref()`；
* 必须使用 `schema.table_name` 引用上游表；
* 可使用 CTE 分步实现复杂逻辑；

✅ 正确示例：

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
)
```

❌ 错误示例：

```sql
with accounts as (
    select *
    from {{{{ ref('stg_salesforce__account') }}}}
)
```

### 4. 禁止交互式命令

* 严禁使用交互式命令（如 vim、nvim、nano、less、more、top、watch、tail -f 等），以避免阻塞运行；
* 只允许使用非交互式方式编辑/写入文件（如重定向 >、>>、tee 或工具 API）；
* 如需查看文件，请使用非交互式命令（如 head -n, tail -n, sed -n '1,100p' 等）。

## 工作流程
1. **编写 SQL 文件**：将所有必需的 SQL 文件写入其指定的子目录。
2. **单表快速验证**：每个 SQL 写完后，可以运行仓库内的 `test_single_sql.py` 进行快速校验， `python test_single_sql.py --table <表名> --layer <层级>`, 例如：
   `python test_single_sql.py --table stg_lever__application --layer staging`。该脚本会在 `xxxx_start.duckdb`上执行单个模型，帮助在不跑完整管道的情况下快速发现问题。
3. **验证**：完成后，执行 `run.py` 来验证管道。

**完成标准：**
确保生成的SQL文件能够通过 `run.py` 成功执行，产出符合业务需求的高质量数据结果。'''

    base_instruction_en = '''You are a professional Data Engineer responsible for implementing a complete SQL data pipeline based on data contract documents.

## Objectives

Generate complete SQL pipeline files according to the specifications in the YAML data contract files under `docs/` (such as `staging_contract.yaml`, etc.) and `config/layer_dependencies.yaml`, ensuring that `run.py` executes successfully and produces the expected results.

## Project Background

* Raw data has been loaded into `xxxx_start.duckdb` (where "xxxx" is a placeholder for the project name, e.g., `greenhouse_start.duckdb`, `google_ads_start.duckdb`, etc.).
* `docs/staging_contract.yaml` defines the table structures, field cleaning, and data quality logic for the **staging layer**.
* `docs/<layer>/*.yaml` (e.g., `docs/intermediate_models/*.yaml`, `docs/marts_models/*.yaml`) defines the data models for each layer, including business logic, field descriptions, and dependencies.
* `xxxx_start.yaml` contains the schema information for the raw data.
* `config/layer_dependencies.yaml` defines the dependency order between layers.

## Implementation Requirements

### 1. Strictly Adhere to Contract Configuration

* Implement **staging layer** SQL according to `staging_contract.yaml`;
* Implement **intermediate**, **marts**, and other layers according to the respective `docs/<layer>/*.yaml`;
* Maintain model dependency order according to `config/layer_dependencies.yaml`;
* All table names, fields, business logic, and grain definitions must exactly match the YAML.

### 2. File and Directory Structure

* SQL code must be placed in directories by layer:
  Example:
  ```
  sql/staging/<table_name>.sql
  sql/intermediate/<model_name>.sql
  sql/marts/<model_name>.sql
  ```
* File names must match the `name` field in the YAML.
* Code style should be consistent, with indentation and CTE naming following best practices.

### 3. SQL Writing Guidelines (DuckDB)
    * Use **pure DuckDB syntax**;
    * **Do NOT** end SQL statements with a semicolon (`;`) at the end of the file.
    * **No dbt syntax**; specifically, do not use `ref()`;
    * Must use the `schema.table_name` format to reference upstream tables;
    * You may use CTEs to implement complex logic in steps;

    ✅ Correct Example:

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
    )
```

* **Incorrect ❌**:
```sql
with accounts as (
    select *
    from {{{{ ref('stg_salesforce__account') }}}}
)
```

### 4. Prohibit interactive commands

* Do NOT use interactive commands (e.g., vim, nvim, nano, less, more, top, watch, tail -f) to avoid blocking runtime;
* Only use non-interactive methods to edit/write files (redirection >, >>, tee, or tool APIs);
* To view files, use non-interactive commands (e.g., head -n, tail -n, sed -n '1,100p').

## Workflow
1. **Write SQL Files**: Write all required SQL files to their designated subdirectories.
2. **Fast per-table test**: After finishing each SQL file, feel free to run `test_single_sql.py` for a quick check, e.g.
   `python test_single_sql.py --table stg_lever__application --layer staging`. This utility runs the single model
   against `lever_start.duckdb` (or your custom DuckDB) so you can iterate without the full config-driven pipeline.
3. **Verify**: Upon completion, execute `run.py` to verify the pipeline.

**Completion Criteria:**
Ensure that the generated SQL files can be run through `run.py` Successfully execute and produce high-quality data results that meet business needs.'''

    if lang == "zh":
        header.append("## 任务说明：\n" + base_instruction_zh)
        header.append("## 当前任务（de-impl 分条执行）")
        header.append(f"本次仅处理以下 YAML：\n- [idx={item['idx']}] ./{path}\n")
        header.append("所有可用 YAML 路径（供参考）：\n" + "\n".join(f"- ./{p}" for p in all_paths) + "\n")
        if existing_sql_paths:
            header.append("已存在的 SQL 文件（可按需引用上游）：\n" + "\n".join(f"- ./{p}" for p in existing_sql_paths) + "\n")
        if forbid_run:
            header.append("[执行策略] 本阶段不要运行 ./run.py；仅编写/更新 SQL。最终由最后的验证 Agent 统一执行与调试。\n")
        header.append("## 该 YAML 的全文\n```yaml\n" + content + "\n```\n")
    else:
        header.append("## Task Description:\n" + base_instruction_en)
        header.append("## Current Task (de-impl, per-YAML)")
        header.append(f"Only handle this YAML in this run:\n- [idx={item['idx']}] ./{path}\n")
        header.append("All YAML paths for reference:\n" + "\n".join(f"- ./{p}" for p in all_paths) + "\n")
        if existing_sql_paths:
            header.append("Existing SQL files (you may reference upstream):\n" + "\n".join(f"- ./{p}" for p in existing_sql_paths) + "\n")
        if forbid_run:
            header.append("[Execution policy] Do NOT run ./run.py in this phase; only write/update SQL. Final validation will be done by the last Validator agent.\n")
        header.append("## YAML Content\n```yaml\n" + content + "\n```\n")

    header.append(_guidelines_block(lang))
    header.append("\n\n" + AGENT_SUFFIX_BY_LANG.get(lang, AGENT_SUFFIX_BY_LANG["zh"]))
    return "\n".join(header)


def build_layer_prompt(layer: str, items: List[dict], lang: str, existing_sql_paths: Optional[List[str]] = None, forbid_run: bool = True) -> str:
    """Build a single prompt that includes multiple YAMLs for a given layer."""
    header: List[str] = []
    if lang == "zh":
        header.append(f"## 任务说明（按层聚合）：{layer}\n")
        header.append("本次需要你基于以下 YAML（同一层）生成/更新对应的 SQL 文件。\n")
        if forbid_run:
            header.append("[执行策略] 严禁在此阶段执行 ./run.py；仅编写/更新 SQL。最终由 Validator 统一执行与调试。\n")
        header.append("### 需要处理的 YAML 列表：\n" + "\n".join(f"- ./{it['path']}" for it in items) + "\n")
        header.append(
            "每个 SQL 完成后，可运行 `python test_single_sql.py --table <表名> --layer <层级>`（例如 `python test_single_sql.py "
            "--table stg_lever__application --layer staging`）在 xxxx_start.duckdb 上快速验证。\n"
        )
    else:
        header.append(f"## Task (layer-batch): {layer}\n")
        header.append("Implement/update SQL for the following YAMLs in this layer.\n")
        if forbid_run:
            header.append("[Execution policy] Do NOT run ./run.py at this stage; only write/update SQL. Validator will execute and debug.\n")
        header.append("### YAMLs to handle:\n" + "\n".join(f"- ./{it['path']}" for it in items) + "\n")
        header.append(
            "After finishing each SQL file, you may run `python test_single_sql.py --table <table> --layer <layer>` "
            "(e.g. `python test_single_sql.py --table stg_lever__application --layer staging`) to validate quickly "
            "against lever_start.duckdb or your custom DuckDB.\n"
        )

    # Optionally include YAML contents.
    # For 'staging' include full YAML; for other layers, only list paths and instruct to open files in workspace.
    if layer == "staging":
        for it in items:
            content = it.get("content", "")
            if lang == "zh":
                header.append(f"\n## YAML 全文：./{it['path']}\n```yaml\n{content}\n```\n")
            else:
                header.append(f"\n## YAML Content: ./{it['path']}\n```yaml\n{content}\n```\n")
    else:
        # Do not inline YAML content for non-staging layers to reduce prompt size
        if lang == "zh":
            header.append("\n[说明] 为控制提示长度，未内嵌 YAML 内容。请在工作区中打开上述 YAML 路径阅读其内容，并据此生成/更新对应 SQL。\n")
            header.append("可以先阅读前置层已生成的 SQL（如下所列）以了解可复用的上游表。\n")
        else:
            header.append("\n[Note] To control prompt size, YAML contents are not inlined. Open the listed YAML paths in the workspace, read them, and implement/update the corresponding SQL.\n")
            header.append("You may first review upstream SQL from previous layers (listed below).\n")

    # Existing SQL files listing (optional)
    if existing_sql_paths:
        if lang == "zh":
            header.append("已存在的 SQL 文件（可参考上游）：\n" + "\n".join(f"- ./{p}" for p in existing_sql_paths) + "\n")
        else:
            header.append("Existing SQL files (for reference):\n" + "\n".join(f"- ./{p}" for p in existing_sql_paths) + "\n")

    header.append(_guidelines_block(lang))
    header.append("\n\n" + AGENT_SUFFIX_BY_LANG.get(lang, AGENT_SUFFIX_BY_LANG.get("zh")))
    return "\n".join(header)


def _normalize_table_name(name: str) -> str:
    base = os.path.basename(str(name))
    stem, _ = os.path.splitext(base)
    return stem.strip().lower()


def find_yaml_item_by_table(inventory: List[dict], table: str) -> Optional[dict]:
    """Locate a YAML inventory item for the given table/model name.

    Strategy:
    - Prefer matching by filename stem (case-insensitive): '<table>.yaml' or '<table>.yml'
    - Fallback: search content for 'name: <table>' or 'table: <table>'
    Returns the first match or None.
    """
    if not table:
        return None
    tnorm = _normalize_table_name(table)

    # First pass: filename stem
    for it in inventory:
        stem = _normalize_table_name(it.get("path", ""))
        if stem == tnorm:
            return it

    # Second pass: content search (best-effort)
    try:
        import re
    except Exception:
        re = None  # type: ignore
    for it in inventory:
        content = it.get("content") or ""
        if not isinstance(content, str):
            continue
        if (f"name: {table}" in content) or (f"table: {table}" in content):
            return it
        if re is not None:
            pat = rf"\b(name|table)\s*:\s*{re.escape(table)}\b"
            if re.search(pat, content):
                return it
    return None


def assign_items_by_table(inventory: List[dict], cfg: dict) -> List[Tuple[str, List[dict]]]:
    """Return an ordered list of (agent_id, [items]) based on 'table' filters.

    Preserves the order of 'agents' and the order of 'filters' per agent.
    Supports fallback to 'layer' if 'table' not present in a filter entry.
    """
    plan: List[Tuple[str, List[dict]]] = []
    for agent in cfg.get("agents", []) or []:
        aid = agent.get("id") or f"agent_{len(plan)+1}"
        filters = (agent.get("assign", {}) or {}).get("filters", []) or []
        items: List[dict] = []
        for f in filters:
            table = f.get("table") or f.get("model") or f.get("name")
            if table:
                it = find_yaml_item_by_table(inventory, str(table))
                if it is not None and it not in items:
                    items.append(it)
                continue
            layer = f.get("layer")
            if layer:
                items.extend([it for it in inventory if it.get("layer") == layer])
        plan.append((aid, items))
    return plan


def run_yaml_item_with_retries(runtime, config: OpenHandsConfig, prompt_lang: str, item: dict, retries: int, max_iterations_override: Optional[int] = None) -> Tuple[bool, int, str, List]:
    # Helper to list existing SQL files each time before prompting
    def _list_existing_sql_paths() -> List[str]:
        try:
            res = runtime.run_action(CmdRunAction(command='find sql -type f -name "*.sql" | sort 2>/dev/null || true'))
            lines = (res.content or "").splitlines()
            return [ln.strip().lstrip('./') for ln in lines if ln.strip()]
        except Exception:
            return []

    # Manage per-agent max_iterations override
    original_max_iters = getattr(config, "max_iterations", None)
    def _apply_override():
        try:
            if isinstance(max_iterations_override, int) and max_iterations_override > 0:
                config.max_iterations = max_iterations_override
        except Exception:
            pass
    def _restore_override():
        try:
            if original_max_iters is not None:
                config.max_iterations = original_max_iters
        except Exception:
            pass

    # First attempt with current SQL inventory
    existing_sql_paths = _list_existing_sql_paths()
    instruction = build_yaml_item_prompt(item, [], prompt_lang, existing_sql_paths)
    state: Optional[State] = None
    try:
        _apply_override()
        try:
            if hasattr(runtime, "status_callback"):
                runtime.status_callback = None
        except Exception:
            pass
        state = asyncio.run(run_controller(
            config=config,
            initial_user_action=MessageAction(content=instruction),
            fake_user_response_fn=make_codeact_user_response(prompt_lang),
            runtime=runtime,
        ))
    except Exception as e:
        logger.warning(f"Agent execution failed on first attempt for idx={item.get('idx')}: {e}")

    # Validate
    success, output = execute_run_py(runtime)
    attempts = 0

    # Retry loop (refresh SQL inventory each attempt)
    while not success and attempts < max(0, int(retries)):
        attempts += 1
        err_prefix = "错误摘要" if prompt_lang == "zh" else "Error summary"
        existing_sql_paths = _list_existing_sql_paths()
        repair_prompt = (
            f"{err_prefix}:\n\n" + (output or "") + "\n\n" +
            build_yaml_item_prompt(item, [], prompt_lang, existing_sql_paths)
        )
        try:
            _apply_override()
            try:
                if hasattr(runtime, "status_callback"):
                    runtime.status_callback = None
            except Exception:
                pass
            state = asyncio.run(run_controller(
                config=config,
                initial_user_action=MessageAction(content=repair_prompt),
                fake_user_response_fn=make_codeact_user_response(prompt_lang),
                runtime=runtime,
            ))
        except Exception as e:
            logger.warning(f"Agent repair attempt {attempts} failed for idx={item.get('idx')}: {e}")
        success, output = execute_run_py(runtime)

    # Prepare history
    histories = []
    try:
        from evaluation.utils.shared import compatibility_for_eval_history_pairs
        histories = compatibility_for_eval_history_pairs(state.history) if state else []
    except Exception:
        pass

    _restore_override()
    return success, attempts, output, histories


# ============ Orchestration per instance ============

def process_instance_agents(instance: pd.Series, metadata, agents_cfg_or_path: Optional[str], reset_logger: bool = True):
    # Logger setup (same as base)
    try:
        import time, random
        stagger = float(os.getenv("DATAAGENT_STAGGER_SEC", "2"))
        if stagger > 0:
            time.sleep(random.random() * stagger)
    except Exception:
        pass

    instance_id = instance["id"]
    if reset_logger:
        from evaluation.utils.shared import reset_logger_for_multiprocessing
        log_dir = os.path.join(metadata.eval_output_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        reset_logger_for_multiprocessing(logger, instance_id, log_dir)
    else:
        logger.info(f"Starting execution for instance {instance_id}.")

    # Load per-project build plan (or fallback config path)
    agents_cfg = load_build_plan_for_instance(instance, agents_cfg_or_path)
    prompt_lang = str(agents_cfg.get("prompt", {}).get("lang", os.getenv("DATAAGENT_PROMPT_LANG", os.getenv("DATAAGENT_LANG", "zh")))).lower()

    runtime = None
    shared_shell = None
    try:
        # Workspace
        task_output_dir = os.path.abspath(os.path.join(metadata.eval_output_dir, instance_id))
        workspace_path = prepare_workspace(instance, task_output_dir)
        workspace_path = os.path.abspath(workspace_path)
        logger.info(f"Using absolute workspace path: {workspace_path}")

        # Config
        config = get_config(metadata, workspace_path)

        # Runtime per YAML (shared workspace files)
        runtime = None
        logger.info("Using per-YAML runtime instances (shared workspace files)")

        global_iter_cap = int(os.getenv("DATAAGENT_GLOBAL_MAX_ITER", "100"))

        def apply_iteration_limit(req: Optional[int] = None) -> Optional[int]:
            """Temporarily clamp config.max_iterations using requested value + global cap."""
            original = getattr(config, "max_iterations", None)
            target = req if isinstance(req, int) and req > 0 else original
            if global_iter_cap > 0:
                if target is None or target <= 0:
                    target = global_iter_cap
                else:
                    target = min(target, global_iter_cap)
            if target and target > 0:
                config.max_iterations = target
            return original

        class _SharedShellRuntime:
            """Reuse a lightweight CLI runtime for helper shell commands."""

            def __init__(self) -> None:
                self._runtime = None
                self._registry = None

            def run(self, command: str):
                if self._runtime is None:
                    self._registry = LLMRegistry(config)
                    self._runtime = create_runtime(config, self._registry)
                    call_async_from_sync(self._runtime.connect)
                    initialize_runtime(self._runtime, instance)
                return self._runtime.run_action(CmdRunAction(command=command))

            def cleanup(self) -> None:
                if self._runtime is not None:
                    cleanup_runtime_container(self._runtime)
                    self._runtime = None
                    self._registry = None

        shared_shell = _SharedShellRuntime()

        # Inventory and assignment
        max_embed = int(os.getenv("DATAAGENT_MAX_YAML_EMBED", "65536"))
        inventory = list_yaml_inventory(instance["source_dir"], max_embed)
        retries = int(agents_cfg.get("validation", {}).get("retries", 5))
        all_histories: List = []

        # If build_plan.yaml provides table-based filters, run agents strictly in order
        has_table_filters = any(
            any((isinstance(flt, dict) and ("table" in flt or "model" in flt or "name" in flt)) for flt in ((ag.get("assign", {}) or {}).get("filters", []) or []))
            for ag in (agents_cfg.get("agents", []) or [])
        )
        if has_table_filters:
            ordered_plan: List[Tuple[str, List[dict]]] = assign_items_by_table(inventory, agents_cfg)

            # Helper to list current SQL files via a short-lived runtime
            def _list_existing_sql_paths() -> List[str]:
                try:
                    res = shared_shell.run('find sql -type f -name "*.sql" | sort 2>/dev/null || true')
                    return [ln.strip().lstrip('./') for ln in (res.content or '').splitlines() if ln.strip()]
                except Exception:
                    return []

            # The last agent is the validator that can run ./run.py
            validator_aid = agents_cfg.get("agents", [{}])[-1].get("id") if agents_cfg.get("agents") else None

            for aid, items in ordered_plan:
                if not items:
                    logger.info(f"Agent {aid} has no assigned items (by table). Skipping.")
                    continue

                is_validator = (validator_aid is not None and aid == validator_aid)
                logger.info(f"Processing Agent={aid} (validator={is_validator}) with {len(items)} item(s)")

                # Apply per-agent max_iterations override
                max_iter_override = None
                try:
                    for agent in agents_cfg.get("agents", []):
                        if agent.get("id") == aid:
                            max_iter_override = agent.get("max_iterations")
                            break
                except Exception:
                    pass

                if not is_validator:
                    # Non-validator: for each YAML item, prompt to write SQL only (no run.py)
                    for item in items:
                        existing_sql_paths = _list_existing_sql_paths()
                        instruction = build_yaml_item_prompt(item, [], prompt_lang, existing_sql_paths, forbid_run=True)

                        original_max_iters = apply_iteration_limit(max_iter_override)
                        try:

                            llm_registry = LLMRegistry(config)
                            runtime = create_runtime(config, llm_registry)
                            call_async_from_sync(runtime.connect)
                            initialize_runtime(runtime, instance)

                            state = asyncio.run(run_controller(
                                config=config,
                                initial_user_action=MessageAction(content=instruction),
                                fake_user_response_fn=make_codeact_user_response(prompt_lang),
                                runtime=runtime,
                            ))
                            try:
                                from evaluation.utils.shared import compatibility_for_eval_history_pairs
                                histories = compatibility_for_eval_history_pairs(state.history) if state else []
                                all_histories.extend(histories)
                            except Exception:
                                pass
                        finally:
                            try:
                                if original_max_iters is not None:
                                    config.max_iterations = original_max_iters
                            except Exception:
                                pass
                            try:
                                cleanup_runtime_container(runtime)
                            except Exception:
                                pass
                            finally:
                                runtime = None
                    # Next agent
                    continue

            # Final validation by validator agent (fresh runtime)
            llm_registry_final = LLMRegistry(config)
            runtime_final = create_runtime(config, llm_registry_final)
            call_async_from_sync(runtime_final.connect)
            initialize_runtime(runtime_final, instance)
            run_success, run_output = execute_run_py(runtime_final)

            if not run_success:
                retries_final = int(agents_cfg.get("validation", {}).get("retries", 5))
                original_max_iters = getattr(config, "max_iterations", None)
                try:
                    if validator_aid:
                        for agent in agents_cfg.get("agents", []):
                            if agent.get("id") == validator_aid:
                                mi = agent.get("max_iterations")
                                if isinstance(mi, int) and mi > 0:
                                    config.max_iterations = mi
                                break
                    attempts = 0
                    while not run_success and attempts < max(0, int(retries_final)):
                        attempts += 1
                        if prompt_lang == "zh":
                            validator_prompt = (
                                "你是最终验证与调试的 Agent（Validator）。现在允许你执行 ./run.py 进行验证。\n"
                                "如果运行失败：请仔细阅读错误输出，定位问题，直接修改对应 SQL 文件（保持 DuckDB 语法与目录约定），"
                                "然后再次执行 ./run.py 复验，重复直到通过或达到重试上限。如果执行 run.py 失败次数大于5次，请停止重试。\n\n"
                                "请避免使用交互式命令；仅使用非交互方式查看/修改文件与运行命令。"
                            )
                        else:
                            validator_prompt = (
                                "You are the final Validator agent. You may now execute ./run.py to validate.\n"
                                "If it fails: read the error output, identify the issue, modify the relevant SQL files "
                                "(pure DuckDB syntax, correct directories), then re-run ./run.py to re-validate, "
                                "repeating until success or retries exhausted.\n\n"
                                "Avoid interactive commands; only use non-interactive methods to view/modify files and run commands."
                            )
                        instruction_v = f"{validator_prompt}\n\nLast run.py output:\n```\n{run_output or ''}\n```\n"
                        try:
                            if hasattr(runtime_final, "status_callback"):
                                runtime_final.status_callback = None
                        except Exception:
                            pass
                        state_v = asyncio.run(run_controller(
                            config=config,
                            initial_user_action=MessageAction(content=instruction_v),
                            fake_user_response_fn=make_codeact_user_response(prompt_lang),
                            runtime=runtime_final,
                        ))
                        run_success, run_output = execute_run_py(runtime_final)
                        try:
                            from evaluation.utils.shared import compatibility_for_eval_history_pairs
                            all_histories.extend(compatibility_for_eval_history_pairs(state_v.history) if state_v else [])
                        except Exception:
                            pass
                finally:
                    try:
                        if original_max_iters is not None:
                            config.max_iterations = original_max_iters
                    except Exception:
                        pass

            # Save results and return
            sql_generated = False
            try:
                from run_infer_de import check_sql_files_generated
                sql_generated = check_sql_files_generated(runtime_final)
            except Exception:
                pass
            finally:
                cleanup_runtime_container(runtime_final)

            simplified_trajectory = simplify_histories(all_histories)
            summary = build_summary(simplified_trajectory)

            save_de_task_results_simple(
                instance_id,
                metadata,
                runtime,
                workspace_path,
                sql_generated,
                run_success,
                run_output,
                all_histories,
                summary,
                instruction=f"Per-agent (table-ordered) run via build_plan.yaml"
            )

            from evaluation.utils.shared import EvalOutput
            return EvalOutput(
                instance_id=instance_id,
                instruction=f"Per-agent orchestration (build_plan)",
                test_result={
                    "sql_files_generated": sql_generated,
                    "run_py_success": run_success,
                    "run_py_output": run_output,
                    "summary": summary,
                },
                metadata=metadata,
                history=all_histories,
                metrics={
                    "sql_generated": sql_generated,
                    "run_success": run_success,
                    "total_steps": summary.get("total_steps", 0),
                    "tool_calls": summary.get("tool_calls", 0),
                },
                error=None,
            )

        # No table-based filters: assign YAMLs by layer/indices mapping
        mapping: Dict[int, str] = {}
        try:
            mapping = assign_yaml_items(inventory, agents_cfg)
        except Exception as e:
            logger.warning(f"Failed to compute assignment mapping, defaulting to empty: {e}")

        # Group items by layer while preserving order
        items_by_layer: Dict[str, List[dict]] = {}
        for it in inventory:
            items_by_layer.setdefault(it.get("layer", "other"), []).append(it)

        # Map each layer to the agent id (from first item's assignment)
        layer_agent: Dict[str, Optional[str]] = {}
        for it in inventory:
            layer = it.get("layer", "other")
            if layer not in layer_agent:
                layer_agent[layer] = mapping.get(it["idx"])  # first item in that layer determines agent id

        # Iterate layers in the canonical order
        for layer in ["staging", "intermediate", "marts", "other"]:
            if layer not in items_by_layer or len(items_by_layer[layer]) == 0:
                continue

            items = items_by_layer[layer]
            aid = layer_agent.get(layer)
            logger.info(f"Processing LAYER={layer} with agent={aid}, items={len(items)}")

            # Gather existing SQL list
            try:
                res = shared_shell.run('find sql -type f -name "*.sql" | sort 2>/dev/null || true')
                existing_sql_paths = [ln.strip().lstrip('./') for ln in (res.content or '').splitlines() if ln.strip()]
            except Exception:
                existing_sql_paths = []

            # Build a single layer-level instruction including multiple YAMLs
            forbid_run = (layer != "marts")  # only forbid for non-final layers
            instruction = build_layer_prompt(layer, items, prompt_lang, existing_sql_paths, forbid_run=forbid_run)

            # Apply per-agent max_iterations override
            max_iter_override = None
            try:
                for agent in agents_cfg.get("agents", []):
                    if agent.get("id") == aid:
                        max_iter_override = agent.get("max_iterations")
                        break
            except Exception:
                pass

            original_max_iters = apply_iteration_limit(max_iter_override)
            try:
                logger.info(f"Effective max_iterations for layer={layer}: {getattr(config, 'max_iterations', None)}")

                # Create per-layer runtime and run once
                llm_registry = LLMRegistry(config)
                runtime = create_runtime(config, llm_registry)
                call_async_from_sync(runtime.connect)
                initialize_runtime(runtime, instance)

                state = asyncio.run(run_controller(
                    config=config,
                    initial_user_action=MessageAction(content=instruction),
                    fake_user_response_fn=make_codeact_user_response(prompt_lang),
                    runtime=runtime,
                ))
            finally:
                try:
                    if original_max_iters is not None:
                        config.max_iterations = original_max_iters
                except Exception:
                    pass

            # Collect history
            try:
                from evaluation.utils.shared import compatibility_for_eval_history_pairs
                histories = compatibility_for_eval_history_pairs(state.history) if state else []
                all_histories.extend(histories)
            except Exception:
                pass

            # Cleanup per-layer runtime
            try:
                cleanup_runtime_container(runtime)
            except Exception:
                pass
            finally:
                runtime = None

        # Per-layer validation: when layer boundary changes or after last item
        def _validate_current_layer():
            try:
                # fresh runtime for validation
                llm_registry_v = LLMRegistry(config)
                runtime_v = create_runtime(config, llm_registry_v)
                call_async_from_sync(runtime_v.connect)
                initialize_runtime(runtime_v, instance)
                ok, out = execute_run_py(runtime_v)
                # only require current/previous layers to succeed; we cannot easily auto-detect layer coverage
                # so we log and do not treat downstream failures as fatal here
                logger.info(f"Layer validation run.py success={ok}")
                cleanup_runtime_container(runtime_v)
                return ok, out
            except Exception as e:
                logger.warning(f"Layer validation failed: {e}")
                return False, str(e)

        # Iterate again to trigger validation when layer changes
        # We already processed items; now we validate after finishing each layer
        run_per_layer = bool(agents_cfg.get("validation", {}).get("run_per_layer", False))
        if run_per_layer:
            last_idx = len(inventory) - 1
            for idx_i, item in enumerate(inventory):
                layer = item.get("layer", "other")
                next_layer = inventory[idx_i + 1].get("layer", "other") if idx_i < last_idx else None
                if next_layer is None or next_layer != layer:
                    # finished a layer
                    logger.info(f"Validating completed layer: {layer}")
                    _validate_current_layer()

        # Final validation (fresh runtime); only Validator agent executes run.py and handles debugging
        llm_registry_final = LLMRegistry(config)
        runtime_final = create_runtime(config, llm_registry_final)
        call_async_from_sync(runtime_final.connect)
        initialize_runtime(runtime_final, instance)
        run_success, run_output = execute_run_py(runtime_final)

        # If failed, hand off to the last agent (validator) to debug by editing SQL and re-running
        if not run_success:
            retries_final = int(agents_cfg.get("validation", {}).get("retries", 5))
            # pick last agent as validator
            validator_aid = None
            try:
                if agents_cfg.get("agents"):
                    validator_aid = agents_cfg["agents"][-1].get("id")
            except Exception:
                pass
            # apply validator-specific max_iterations if configured
            validator_override = None
            if validator_aid:
                for agent in agents_cfg.get("agents", []):
                    if agent.get("id") == validator_aid:
                        mi = agent.get("max_iterations")
                        if isinstance(mi, int) and mi > 0:
                            validator_override = mi
                        break
            original_max_iters = apply_iteration_limit(validator_override)
            try:
                attempts = 0
                while not run_success and attempts < max(0, int(retries_final)):
                    attempts += 1
                    # Build validator instruction (allow running ./run.py and using errors to patch SQL)
                    if prompt_lang == "zh":
                        validator_prompt = (
                            "你是最终验证与调试的 Agent（Validator）。现在允许你执行 ./run.py 进行验证。\n"
                            "如果运行失败：请仔细阅读错误输出，定位问题，直接修改对应 SQL 文件（保持 DuckDB 语法与目录约定），"
                            "然后再次执行 ./run.py 复验，重复直到通过或达到重试上限。\n\n"
                            "请避免使用交互式命令；仅使用非交互方式查看/修改文件与运行命令。"
                        )
                    else:
                        validator_prompt = (
                            "You are the final Validator agent. You may now execute ./run.py to validate.\n"
                            "If it fails: read the error output, identify the issue, modify the relevant SQL files "
                            "(pure DuckDB syntax, correct directories), then re-run ./run.py to re-validate, "
                            "repeating until success or retries exhausted.\n\n"
                            "Avoid interactive commands; only use non-interactive methods to view/modify files and run commands."
                        )
                    # Include the last run output to provide immediate context
                    instruction_v = f"{validator_prompt}\n\nLast run.py output:\n```\n{run_output or ''}\n```\n"
                    try:
                        if hasattr(runtime_final, "status_callback"):
                            runtime_final.status_callback = None
                    except Exception:
                        pass
                    state_v = asyncio.run(run_controller(
                        config=config,
                        initial_user_action=MessageAction(content=instruction_v),
                        fake_user_response_fn=make_codeact_user_response(prompt_lang),
                        runtime=runtime_final,
                    ))
                    # check again
                    run_success, run_output = execute_run_py(runtime_final)
                    # collect histories
                    try:
                        from evaluation.utils.shared import compatibility_for_eval_history_pairs
                        all_histories.extend(compatibility_for_eval_history_pairs(state_v.history) if state_v else [])
                    except Exception:
                        pass
            finally:
                try:
                    if original_max_iters is not None:
                        config.max_iterations = original_max_iters
                except Exception:
                    pass

        # Check whether any SQL files were generated
        sql_generated = False
        try:
            from run_infer_de import check_sql_files_generated
            sql_generated = check_sql_files_generated(runtime_final)
        except Exception:
            pass
        finally:
            cleanup_runtime_container(runtime_final)

        simplified_trajectory = simplify_histories(all_histories)
        summary = build_summary(simplified_trajectory)

        save_de_task_results_simple(
            instance_id,
            metadata,
            runtime,
            workspace_path,
            sql_generated,
            run_success,
            run_output,
            all_histories,
            summary,
            instruction=f"Orchestrated per-YAML agents run (config-driven)"
        )

        from evaluation.utils.shared import EvalOutput
        return EvalOutput(
            instance_id=instance_id,
            instruction=f"Per-YAML agents orchestration",
            test_result={
                "sql_files_generated": sql_generated,
                "run_py_success": run_success,
                "run_py_output": run_output,
                "summary": summary,
            },
            metadata=metadata,
            history=all_histories,
            metrics={
                "sql_generated": sql_generated,
                "run_success": run_success,
                "total_steps": summary.get("total_steps", 0),
                "tool_calls": summary.get("tool_calls", 0),
            },
            error=None,
        )

    except Exception as e:
        logger.error(f"Error in process_instance_agents for {instance_id}: {e}")
        try:
            # Best-effort partial save
            save_de_task_results_simple(
                instance_id,
                metadata,
                runtime,
                locals().get("workspace_path", ""),
                False,
                False,
                str(e),
                [],
                {},
                instruction="Orchestrated per-YAML agents run (failed)",
                error_message=str(e),
            )
        except Exception:
            pass
        from evaluation.utils.shared import EvalOutput
        return EvalOutput(
            instance_id=instance_id,
            instruction=f"Per-YAML agents orchestration",
            test_result={"result": {"status": "error", "message": str(e)}},
            metadata=metadata,
            history=[],
            metrics={"sql_generated": False, "run_success": False},
            error=str(e),
        )
    finally:
        try:
            cleanup_runtime_container(runtime)
        except Exception as e:
            logger.warning(f"Runtime cleanup failed: {e}")
        finally:
            try:
                if shared_shell:
                    shared_shell.cleanup()
            except Exception:
                pass


# ============ CLI entry ============

def main():
    parser = argparse.ArgumentParser(description="Run DATAAGENT DE (per-YAML agents orchestrator)")
    parser.add_argument('-c', '--agent-cls', type=str, default='CodeActAgent', help='Default agent class to use')
    parser.add_argument('-l', '--llm-config', type=str, required=True, help='LLM configuration')
    parser.add_argument('-i', '--max-iterations', type=int, default=30, help='Maximum iterations (default agent)')
    parser.add_argument('-n', '--num-tasks', type=int, default=1, help='Number of tasks to process')
    parser.add_argument('--task-ids', type=str, help='Specific task IDs to process (comma-separated)')
    parser.add_argument('--skip-num', type=int, default=0, help='Number of tasks to skip from beginning')
    parser.add_argument('-j', '--concurrency', type=int, default=1, help='Number of parallel workers to run tasks')
    parser.add_argument('--lang', choices=['zh','en'], default='zh', help='Dataset language selector (affects ENV)')
    parser.add_argument('--prompt-lang', choices=['zh','en'], default=None, help='Prompt language; default to --lang')
    parser.add_argument('--task-type', choices=['impl'], default='impl', help='Filter tasks by type (impl only for multi-agent)')
    parser.add_argument('--agents-config', type=str, default='auto', help='Config path; default to per-project build_plan.yaml ("auto")')
    parser.add_argument('--exp-name', type=str, default='default', help='Custom experiment name for output directory')
    parser.add_argument('--overwrite', action='store_true', help='Re-run tasks even if a successful result already exists')
    args = parser.parse_args()

    # ENV
    lang = args.lang or os.getenv("DATAAGENT_LANG", "zh")
    prompt_lang = args.prompt_lang or args.lang or os.getenv("DATAAGENT_PROMPT_LANG", lang)
    os.environ["DATAAGENT_LANG"] = lang
    os.environ["DATAAGENT_PROMPT_LANG"] = prompt_lang
    os.environ["DATAAGENT_TASK_TYPE"] = "de-impl"

    logger.info("Starting DATAAGENT DE (per-YAML orchestrator) with parameters:")
    logger.info(f"  Default Agent: {args.agent_cls}")
    logger.info(f"  LLM Config: {args.llm_config}")
    logger.info(f"  Max Iterations: {args.max_iterations}")
    logger.info(f"  Number of Tasks: {args.num_tasks}")
    logger.info(f"  Skip Number: {args.skip_num}")
    logger.info(f"  Concurrency: {args.concurrency}")
    logger.info(f"  Lang: {lang}")
    logger.info(f"  Prompt Lang: {prompt_lang}")
    logger.info(f"  Task Type Filter: {args.task_type}")
    logger.info(f"  Experiment Name: {args.exp_name}")
    logger.info(f"  Overwrite: {args.overwrite}")
    logger.info(f"  Agents Config: {args.agents_config} (use 'auto' for per-project build_plan.yaml)")
    if args.task_ids:
        logger.info(f"  Task IDs: {args.task_ids}")

    # Dataset
    dataset = load_de_dataset(args.task_type, lang)
    if dataset.empty:
        logger.error("No DE tasks found in dataset!")
        raise SystemExit(1)

    # LLM config
    llm_config = get_llm_config_arg(args.llm_config)
    if llm_config is None:
        raise ValueError(f"Could not find LLM config: --llm_config {args.llm_config}")

    eval_ids = [id.strip() for id in args.task_ids.split(',')] if args.task_ids else None

    from evaluation.utils.shared import make_metadata, run_evaluation
    exp_name = _sanitize_exp_name(args.exp_name or "default")
    model_path = _model_path_from_llm(llm_config)
    lang_suffix = "_zh" if str(lang).lower().startswith("zh") else ""
    base_dir = os.path.abspath(os.path.join('evaluation_output', 'dacomp_de_impl_multi_agent', f"{model_path}_{exp_name}{lang_suffix}"))
    os.makedirs(base_dir, exist_ok=True)

    metadata = make_metadata(
        llm_config,
        'dacomp_de_impl_multi_agent',
        args.agent_cls,
        args.max_iterations,
        os.environ.get('OPENHANDS_VERSION', 'v0.53.0'),
        base_dir,
        details={"exp_name": exp_name},
        eval_output_path_override=base_dir,
    )

    output_file = os.path.join(metadata.eval_output_dir, 'output.jsonl')
    if not args.overwrite:
        completed_ids = []
        for _, row in dataset.iterrows():
            instance_id = row['instance_id']
            if is_task_complete(instance_id, metadata.eval_output_dir):
                completed_ids.append(instance_id)
        if completed_ids:
            dataset = dataset[~dataset['instance_id'].isin(completed_ids)]
            logger.info(f"Skipping {len(completed_ids)} completed tasks (overwrite disabled).")
        logger.info(f"Remaining tasks after skip check: {len(dataset)}")
        if dataset.empty:
            logger.info("No DE tasks to run after applying overwrite/skip filters; exiting.")
            raise SystemExit(0)

    instances = prepare_dataset_custom(dataset, output_file, args.num_tasks, eval_ids, args.skip_num)
    if instances.empty:
        logger.error("No instances to process after filtering!")
        raise SystemExit(1)

    logger.info(f"Processing {len(instances)} instances with orchestrator")

    progress_file = os.path.join(metadata.eval_output_dir, 'progress.json')
    with open(progress_file, 'w') as f:
        json.dump({"total": len(instances), "completed": 0, "status": "running"}, f)

    try:
        workers = max(1, min(int(args.concurrency), len(instances)))
        # Use evaluation runner with our process function
        run_evaluation(instances, metadata, output_file, workers, lambda inst, meta, reset=True: process_instance_agents(inst, meta, args.agents_config, reset))
        with open(progress_file, 'w') as f:
            json.dump({"total": len(instances), "completed": len(instances), "status": "completed"}, f)
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        with open(progress_file, 'w') as f:
            json.dump({"total": len(instances), "completed": 0, "status": "failed", "error": str(e)}, f)
        raise


if __name__ == '__main__':
    main()
