from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
from loguru import logger

from .config import VISION_CAPABLE_MODEL_CONFIGS, model_config
from .prompts import get_gsb_prompt, get_rubric_prompt
from .runners import run_gsb_channel, run_rubrics_tasks
from .tasks import (
    EvaluationTask,
    extract_total_score,
    is_valid_gsb_response,
    is_valid_rubrics_response,
    to_optional_float,
)
from .tasks_loader import GSB_REF_KEYS, load_task_metadata

EVALUATION_MODE_LABEL = "full"
_NO_IMAGE_VIS_RESPONSE = json.dumps(
    {
        "洞察呈现与可视化": {
            "分析": "候选报告未提供任何图片，视觉维度自动计为 0 分。",
            "得分": 0,
        },
        "Insight Presentation & Visualization": {
            "analysis": "No candidate images were detected, so the visualization score defaults to 0.",
            "score": 0,
        },
        "总得分": 0,
        "total_score": 0,
    },
    ensure_ascii=False,
    indent=4,
)
NO_IMAGE_VIS_RESULT_TEXT = f"```json\n{_NO_IMAGE_VIS_RESPONSE}\n```"


def build_tasks(
    model_file: Path,
    task_metadata: Dict[str, Dict[str, Any]],
    existing_rows: Dict[str, Dict[str, Any]],
    rubrics_enabled: bool,
    gsb_text_enabled: bool,
    gsb_vis_enabled: bool,
    rubric_prompt_template: str,
    gsb_text_prompt_template: str,
    gsb_vis_prompt_template: str,
) -> List[EvaluationTask]:
    tasks: List[EvaluationTask] = []
    needs_gsb = gsb_text_enabled or gsb_vis_enabled
    with model_file.open("r", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            record = json.loads(raw)
            instance_id = record["instance_id"]
            trajectory = record.get("trajectory") or ""
            answer = record.get("answer") or ""
            answer_path_raw = record.get("answer_path")
            answer_path = Path(answer_path_raw) if answer_path_raw else None
            image_paths = [
                Path(image_str)
                for image_str in record.get("answer_images", [])  # type: ignore[list-item]
            ]
            meta = task_metadata.get(instance_id)
            if not meta:
                logger.warning(f"No metadata for instance {instance_id}, skip.")
                continue

            gsb_refs: Dict[str, str] = {}
            reference_images: Dict[str, List[Path]] = {}
            refs_meta = meta.get("gsb_refs")
            refs_images_meta = meta.get("gsb_ref_images")
            for key in GSB_REF_KEYS:
                text_value = ""
                if isinstance(refs_meta, dict):
                    raw_text = refs_meta.get(key, "")
                    if isinstance(raw_text, str):
                        text_value = raw_text
                else:
                    raw_text = meta.get(key, "")
                    if isinstance(raw_text, str):
                        text_value = raw_text
                gsb_refs[key] = text_value

                images_value: List[Path] = []
                raw_images: Optional[List[Any]] = None
                if isinstance(refs_images_meta, dict):
                    candidate = refs_images_meta.get(key, [])
                    if isinstance(candidate, list):
                        raw_images = candidate
                if raw_images:
                    for image_item in raw_images:
                        if not isinstance(image_item, str):
                            continue
                        image_path = Path(image_item)
                        if not image_path.exists():
                            logger.warning(
                                "Reference image not found",
                                instance_id=instance_id,
                                reference=key,
                                image=str(image_path),
                            )
                            continue
                        images_value.append(image_path)
                reference_images[key] = images_value

            references: Dict[str, str] = {}
            if needs_gsb:
                suffix = instance_id.split("-")[-1]
                ref_key = f"DACOMP-{int(suffix):03}@dacomp"
                references = {
                    key: value for key, value in gsb_refs.items() if value
                }
                if not references:
                    logger.warning(
                        "No reference reports found for GSB evaluation",
                        instance_id=instance_id,
                        ref_key=ref_key,
                    )

            existing = existing_rows.get(instance_id, {})
            existing_rubrics = existing.get("rubrics_result")
            if isinstance(existing_rubrics, float) and pd.isna(existing_rubrics):
                existing_rubrics = None
            if isinstance(existing_rubrics, str) and existing_rubrics.strip():
                if not is_valid_rubrics_response(existing_rubrics):
                    logger.warning(
                        "Cached rubrics response for {} is invalid JSON, will rerun.",
                        instance_id,
                    )
                    existing_rubrics = None
            existing_total = to_optional_float(existing.get("rubrics_total_score"))
            if existing_total is None and isinstance(existing_rubrics, str):
                existing_total = extract_total_score(existing_rubrics)
            def parse_existing_gsb(raw_value: Any, label: str) -> Dict[str, str]:
                records: Dict[str, str] = {}
                if not isinstance(raw_value, str) or not raw_value.strip():
                    return records
                try:
                    payload = json.loads(raw_value)
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to decode existing %s for %s", label, instance_id
                    )
                    return records
                if not isinstance(payload, dict):
                    logger.warning(
                        "Unexpected %s structure for %s", label, instance_id
                    )
                    return records
                for ref_model, content in payload.items():
                    if not (isinstance(content, str) and content.strip()):
                        continue
                    if is_valid_gsb_response(content):
                        records[ref_model] = content
                    else:
                        logger.warning(
                            "Cached %s response for %s/%s is invalid JSON, will rerun.",
                            label,
                            instance_id,
                            ref_model,
                        )
                return records

            existing_gsb_text = parse_existing_gsb(
                existing.get("gsb_text_results") or existing.get("gsb_results"),
                "gsb_text_results",
            )
            existing_gsb_vis = parse_existing_gsb(
                existing.get("gsb_vis_results"), "gsb_vis_results"
            )

            pending_text_refs: set[str] = set()
            pending_vis_refs: set[str] = set()
            if gsb_text_enabled:
                for ref_model in references:
                    raw = existing_gsb_text.get(ref_model)
                    if not (isinstance(raw, str) and raw.strip()):
                        pending_text_refs.add(ref_model)
            if gsb_vis_enabled:
                for ref_model in references:
                    raw = existing_gsb_vis.get(ref_model)
                    if not (isinstance(raw, str) and raw.strip()):
                        pending_vis_refs.add(ref_model)

            task = EvaluationTask(
                instance_id=instance_id,
                model_name=model_file.stem,
                query=meta.get("instruction", ""),
                rubrics=meta.get("rubrics", ""),
                trajectory=trajectory,
                answer=answer,
                answer_path=answer_path,
                answer_images=image_paths,
                reference_reports=references,
                rubrics_result=existing_rubrics,
                rubrics_total_score=existing_total,
                gsb_text_results=existing_gsb_text,
                gsb_vis_results=existing_gsb_vis,
                gsb_refs=gsb_refs,
                gsb_text_pending_refs=pending_text_refs,
                gsb_vis_pending_refs=pending_vis_refs,
                reference_images=reference_images,
                rubric_prompt_template=rubric_prompt_template,
                gsb_text_prompt_template=gsb_text_prompt_template,
                gsb_vis_prompt_template=gsb_vis_prompt_template,
            )
            task.need_rubrics = rubrics_enabled and (
                not task.rubrics_result or task.rubrics_total_score is None
            )
            task.need_gsb_text = gsb_text_enabled and bool(pending_text_refs)
            task.need_gsb_vis = gsb_vis_enabled and bool(pending_vis_refs)
            if gsb_vis_enabled and not image_paths:
                if references:
                    task.gsb_vis_results = {
                        ref_model: NO_IMAGE_VIS_RESULT_TEXT for ref_model in references
                    }
                else:
                    task.gsb_vis_results = {}
                task.gsb_vis_pending_refs.clear()
                task.need_gsb_vis = False
                if references:
                    logger.info(
                        "GSB-visual skipped for %s: no answer images detected; assigned 0.",
                        instance_id,
                    )
            tasks.append(task)
    return tasks


def evaluate_models(
    model_files: List[Path],
    metadata_source: Path,
    rubrics_model: str,
    gsb_model_text: str,
    gsb_model_vis: str,
    output_dir: Path,
    max_workers: int = 1,
    language: str = "zh",
) -> List[Path]:
    task_metadata = load_task_metadata(metadata_source)
    rubric_prompt_template = get_rubric_prompt(language)
    gsb_text_prompt_template = get_gsb_prompt(language, "text")
    gsb_vis_prompt_template = get_gsb_prompt(language, "visual")

    if not rubrics_model or not gsb_model_text or not gsb_model_vis:
        raise ValueError(
            "rubrics_model, gsb_model_text, and gsb_model_vis must all be provided."
        )

    embedded_refs_available = False
    for meta in task_metadata.values():
        refs = meta.get("gsb_refs")
        if isinstance(refs, dict):
            if any(refs.get(key) for key in GSB_REF_KEYS):
                embedded_refs_available = True
                break
        else:
            if any(meta.get(key) for key in GSB_REF_KEYS):
                embedded_refs_available = True
                break
    if not embedded_refs_available:
        raise ValueError(
            "GSB evaluation requires gsb_ref_* fields in the metadata source."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    result_paths: List[Path] = []

    def resolve_model_name(config_name: Optional[str]) -> Optional[str]:
        if not config_name:
            return None
        info = model_config.get(config_name)
        if not info:
            logger.warning(f"Model config {config_name} not found in config map.")
            return None
        return info.get("model_name")

    def model_supports_images(config_name: Optional[str]) -> bool:
        if not config_name:
            return False
        return config_name in VISION_CAPABLE_MODEL_CONFIGS

    def sanitize(value: Optional[str]) -> str:
        if not value:
            return "none"
        safe = []
        for ch in value:
            safe.append(ch if ch.isalnum() or ch in "-_" else "-")
        return "".join(safe)

    for model_file in model_files:
        logger.info(f"Evaluating {model_file.name}")

        rubrics_config = rubrics_model
        gsb_text_config = gsb_model_text
        gsb_vis_config = gsb_model_vis

        rubrics_model_name = resolve_model_name(rubrics_config)
        gsb_text_model_name = resolve_model_name(gsb_text_config)
        gsb_vis_model_name = resolve_model_name(gsb_vis_config)
        gsb_text_enabled = bool(gsb_text_config)
        gsb_vis_enabled = bool(gsb_vis_config)
        gsb_vis_allow_images = model_supports_images(gsb_vis_config)
        if gsb_vis_enabled and not gsb_vis_allow_images:
            logger.warning(
                "GSB visualization model %s is not vision-capable; images will be skipped.",
                gsb_vis_config,
            )

        filename = "__".join(
            [
                model_file.stem,
                f"rubrics-{sanitize(rubrics_config)}",
                f"textgsb-{sanitize(gsb_text_config)}",
                f"visgsb-{sanitize(gsb_vis_config)}",
            ]
        )
        output_path = output_dir / f"{filename}.csv"

        existing_rows_raw: Dict[str, Dict[str, Any]] = {}
        if output_path.exists():
            try:
                existing_df = pd.read_csv(output_path)
                for _, row in existing_df.iterrows():
                    instance_id = row.get("instance_id")
                    if isinstance(instance_id, str):
                        existing_rows_raw[instance_id] = row.to_dict()
            except Exception as exc:  # noqa: BLE001
                logger.error(f"Failed to load existing results from {output_path}: {exc}")

        def normalize_row(row_dict: Dict[str, Any]) -> Dict[str, Any]:
            normalized: Dict[str, Any] = {}
            for key, value in row_dict.items():
                if isinstance(value, float) and pd.isna(value):
                    normalized[key] = None
                else:
                    normalized[key] = value
            instance_label = row_dict.get("instance_id")
            rubrics_raw = normalized.get("rubrics_result")
            if isinstance(rubrics_raw, str) and rubrics_raw.strip():
                if not is_valid_rubrics_response(rubrics_raw):
                    logger.warning(
                        "Dropping invalid cached rubrics_result for {}",
                        instance_label,
                    )
                    normalized["rubrics_result"] = None
                    normalized["rubrics_total_score"] = None
            def normalize_gsb_column(column_name: str) -> None:
                raw_value = normalized.get(column_name)
                if not isinstance(raw_value, str) or not raw_value.strip():
                    normalized[column_name] = None
                    return
                try:
                    payload = json.loads(raw_value)
                except json.JSONDecodeError:
                    logger.warning(
                        "Dropping invalid cached %s for %s",
                        column_name,
                        instance_label,
                    )
                    normalized[column_name] = None
                    return
                if not isinstance(payload, dict):
                    normalized[column_name] = None
                    return
                cleaned: Dict[str, str] = {}
                dirty_refs: List[str] = []
                for ref_key, content in payload.items():
                    if isinstance(content, str) and content.strip():
                        if is_valid_gsb_response(content):
                            cleaned[ref_key] = content
                        else:
                            dirty_refs.append(ref_key)
                    else:
                        dirty_refs.append(ref_key)
                if dirty_refs:
                    logger.warning(
                        "Dropping invalid %s refs %s for %s",
                        column_name,
                        ", ".join(dirty_refs),
                        instance_label,
                    )
                normalized[column_name] = (
                    json.dumps(cleaned, ensure_ascii=False) if cleaned else None
                )

            if "gsb_text_results" in normalized:
                normalize_gsb_column("gsb_text_results")
            elif "gsb_results" in normalized:
                normalize_gsb_column("gsb_results")
                normalized["gsb_text_results"] = normalized.get("gsb_results")
            if "gsb_vis_results" in normalized:
                normalize_gsb_column("gsb_vis_results")
            return normalized

        rows_map: Dict[str, Dict[str, Any]] = {
            key: normalize_row(value) for key, value in existing_rows_raw.items()
        }
        rows_lock = threading.Lock()

        def write_rows() -> None:
            df = pd.DataFrame(rows_map.values())
            output_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_path, index=False)

        def merge_task(task: EvaluationTask, commit: bool) -> None:
            with rows_lock:
                previous = rows_map.get(task.instance_id, {})
                row = dict(previous)
                row.update(
                    {
                        "instance_id": task.instance_id,
                        "model_name": task.model_name,
                        "rubrics_model_config": rubrics_config,
                        "rubrics_model_name": rubrics_model_name,
                        "gsb_text_model_config": gsb_text_config,
                        "gsb_text_model_name": gsb_text_model_name,
                        "gsb_vis_model_config": gsb_vis_config,
                        "gsb_vis_model_name": gsb_vis_model_name,
                        "gsb_model_config": gsb_text_config or gsb_vis_config,
                        "gsb_model_name": gsb_text_model_name or gsb_vis_model_name,
                        "evaluation_mode": EVALUATION_MODE_LABEL,
                    }
                )
                if task.rubrics_result is not None:
                    row["rubrics_result"] = task.rubrics_result
                elif "rubrics_result" not in row:
                    row["rubrics_result"] = previous.get("rubrics_result")
                if task.rubrics_total_score is not None:
                    row["rubrics_total_score"] = task.rubrics_total_score
                elif "rubrics_total_score" not in row:
                    row["rubrics_total_score"] = previous.get("rubrics_total_score")

                for ref_key in GSB_REF_KEYS:
                    row[ref_key] = task.gsb_refs.get(ref_key, previous.get(ref_key, ""))

                if task.gsb_text_results:
                    serialized = json.dumps(
                        task.gsb_text_results,
                        ensure_ascii=False,
                    )
                    row["gsb_text_results"] = serialized
                    row["gsb_results"] = serialized
                elif "gsb_text_results" not in row:
                    row["gsb_text_results"] = previous.get("gsb_text_results") or previous.get(
                        "gsb_results"
                    )
                    row.setdefault("gsb_results", row["gsb_text_results"])

                if task.gsb_vis_results:
                    row["gsb_vis_results"] = json.dumps(
                        task.gsb_vis_results,
                        ensure_ascii=False,
                    )
                elif "gsb_vis_results" not in row:
                    row["gsb_vis_results"] = previous.get("gsb_vis_results")

                if "gsb_total_score" not in row:
                    row["gsb_total_score"] = previous.get("gsb_total_score")

                rows_map[task.instance_id] = row
                if commit:
                    write_rows()

        rubrics_enabled = bool(rubrics_config)

        evaluations = build_tasks(
            model_file=model_file,
            task_metadata=task_metadata,
            existing_rows=rows_map,
            rubrics_enabled=rubrics_enabled,
            gsb_text_enabled=gsb_text_enabled,
            gsb_vis_enabled=gsb_vis_enabled,
            rubric_prompt_template=rubric_prompt_template,
            gsb_text_prompt_template=gsb_text_prompt_template,
            gsb_vis_prompt_template=gsb_vis_prompt_template,
        )
        if not evaluations:
            logger.warning(f"No evaluations built for {model_file.name}")
            continue

        for task in evaluations:
            merge_task(task, commit=False)

        def log_progress(prefix: str, total_count: int) -> Callable[[int], None]:
            def _log(done: int) -> None:
                if total_count == 0:
                    logger.info(f"{prefix}: {done} completed.")
                else:
                    logger.info(f"{prefix}: {done}/{total_count} completed.")

            return _log

        total_instances = len(evaluations)

        worker_threads: List[threading.Thread] = []

        if rubrics_enabled:
            if not rubrics_config:
                raise ValueError("rubrics_model is required for rubrics evaluation.")
            rubrics_pending = sum(task.need_rubrics for task in evaluations)
            logger.info(
                f"Rubrics queue ({model_file.stem}): {rubrics_pending} pending / "
                f"{total_instances} total"
            )
            total_to_run = rubrics_pending
            start_done = sum(
                1
                for task in evaluations
                if task.rubrics_result is not None and not task.need_rubrics
            )
            progress_cb = log_progress(
                f"Rubrics progress ({model_file.stem})", start_done + total_to_run
            )

            def run_rubrics_worker() -> None:
                run_rubrics_tasks(
                    evaluations,
                    rubrics_config,
                    max_workers=max_workers,
                    on_finish=lambda task: merge_task(task, True),
                    progress=(start_done, start_done + total_to_run, progress_cb),
                )

            thread = threading.Thread(
                target=run_rubrics_worker,
                name=f"RubricsWorker-{model_file.stem}",
            )
            thread.start()
            worker_threads.append(thread)

        if gsb_text_enabled:
            if not gsb_text_config:
                raise ValueError("gsb-model-text is required when text channel is enabled.")
            gsb_pending = sum(task.need_gsb_text for task in evaluations)
            logger.info(
                f"GSB-text queue ({model_file.stem}): {gsb_pending} pending / "
                f"{total_instances} total"
            )
            total_to_run = gsb_pending
            start_done = sum(
                1
                for task in evaluations
                if task.gsb_text_results and not task.need_gsb_text
            )
            progress_cb = log_progress(
                f"GSB-text progress ({model_file.stem})", start_done + total_to_run
            )

            def run_gsb_text_worker() -> None:
                run_gsb_channel(
                    evaluations,
                    gsb_text_config,
                    include_images=False,
                    channel="text",
                    max_workers=max_workers,
                    on_finish=lambda task: merge_task(task, True),
                    progress=(start_done, start_done + total_to_run, progress_cb),
                )

            thread = threading.Thread(
                target=run_gsb_text_worker,
                name=f"GSBTextWorker-{model_file.stem}",
            )
            thread.start()
            worker_threads.append(thread)

        if gsb_vis_enabled:
            if not gsb_vis_config:
                raise ValueError("gsb-model-vis is required when visualization channel is enabled.")
            gsb_pending = sum(task.need_gsb_vis for task in evaluations)
            logger.info(
                f"GSB-visual queue ({model_file.stem}): {gsb_pending} pending / "
                f"{total_instances} total"
            )
            total_to_run = gsb_pending
            start_done = sum(
                1
                for task in evaluations
                if task.gsb_vis_results and not task.need_gsb_vis
            )
            progress_cb = log_progress(
                f"GSB-visual progress ({model_file.stem})", start_done + total_to_run
            )

            def run_gsb_visual_worker() -> None:
                run_gsb_channel(
                    evaluations,
                    gsb_vis_config,
                    include_images=gsb_vis_allow_images,
                    channel="vis",
                    max_workers=max_workers,
                    on_finish=lambda task: merge_task(task, True),
                    progress=(start_done, start_done + total_to_run, progress_cb),
                )

            thread = threading.Thread(
                target=run_gsb_visual_worker,
                name=f"GSBVisualWorker-{model_file.stem}",
            )
            thread.start()
            worker_threads.append(thread)

        for thread in worker_threads:
            thread.join()

        with rows_lock:
            write_rows()
        result_paths.append(output_path)

    return result_paths
