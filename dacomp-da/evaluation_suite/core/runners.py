from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, List, Optional, Tuple

from loguru import logger

from .tasks import (
    EvaluationTask,
    MAX_GSB_ATTEMPTS,
    MAX_RUBRICS_ATTEMPTS,
)


def run_rubrics_tasks(
    tasks: Iterable[EvaluationTask],
    config_name: str,
    max_workers: int,
    on_finish: Optional[Callable[[EvaluationTask], None]] = None,
    progress: Optional[Tuple[int, int, Callable[[int], None]]] = None,
) -> None:
    tracked_tasks = [task for task in tasks if task.need_rubrics]
    if not tracked_tasks:
        return
    completed = 0
    update_progress = progress[2] if progress else None
    pending_count = progress[0] if progress else 0

    while True:
        pending = [task for task in tracked_tasks if task.need_rubrics]
        if not pending:
            return
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(task.eval_rubrics, config_name): task for task in pending
            }
            for future in as_completed(future_map):
                task = future_map[future]
                success = False
                try:
                    future.result()
                    success = not task.need_rubrics
                except Exception as exc:  # noqa: BLE001
                    logger.error(f"Rubrics eval failed for {task.instance_id}: {exc}")
                finally:
                    if on_finish:
                        on_finish(task)
                    if success:
                        completed += 1
                        if update_progress:
                            update_progress(pending_count + completed)

        stuck_tasks = [
            task
            for task in tracked_tasks
            if task.need_rubrics and task.rubrics_attempts >= MAX_RUBRICS_ATTEMPTS
        ]
        if not stuck_tasks:
            continue
        logger.warning(
            "Rubrics evaluation reached the retry limit (%d attempts) for: %s. "
            "Skipping these instances.",
            MAX_RUBRICS_ATTEMPTS,
            ", ".join(task.instance_id for task in stuck_tasks),
        )
        for task in stuck_tasks:
            task.need_rubrics = False


def run_gsb_channel(
    tasks: Iterable[EvaluationTask],
    config_name: str,
    *,
    include_images: bool,
    channel: str,
    max_workers: int,
    on_finish: Optional[Callable[[EvaluationTask], None]] = None,
    progress: Optional[Tuple[int, int, Callable[[int], None]]] = None,
) -> None:
    attr_name = "need_gsb_text" if channel == "text" else "need_gsb_vis"
    prompt_attr = (
        "gsb_text_prompt_template" if channel == "text" else "gsb_vis_prompt_template"
    )
    tracked_tasks = [task for task in tasks if getattr(task, attr_name)]
    if not tracked_tasks:
        return
    completed = 0
    update_progress = progress[2] if progress else None
    pending_count = progress[0] if progress else 0

    while True:
        pending = [task for task in tracked_tasks if getattr(task, attr_name)]
        if not pending:
            return
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(
                    task.eval_gsb,
                    config_name=config_name,
                    include_images=include_images,
                    channel=channel,
                    prompt_template=getattr(task, prompt_attr),
                ): task
                for task in pending
            }
            for future in as_completed(future_map):
                task = future_map[future]
                success = False
                try:
                    future.result()
                    success = not getattr(task, attr_name)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        f"GSB eval failed for {task.instance_id} ({channel}): {exc}"
                    )
                finally:
                    if on_finish:
                        on_finish(task)
                    if success:
                        completed += 1
                        if update_progress:
                            update_progress(pending_count + completed)

        stuck_refs = []
        for task in tracked_tasks:
            updated = False
            pending_refs = (
                task.gsb_text_pending_refs
                if channel == "text"
                else task.gsb_vis_pending_refs
            )
            attempts = (
                task.gsb_text_attempts if channel == "text" else task.gsb_vis_attempts
            )
            for ref_model in list(pending_refs):
                if attempts.get(ref_model, 0) >= MAX_GSB_ATTEMPTS:
                    stuck_refs.append(f"{task.instance_id}:{ref_model}")
                    pending_refs.discard(ref_model)
                    updated = True
            if not updated:
                continue
            if channel == "text":
                task.need_gsb_text = bool(pending_refs)
            else:
                task.need_gsb_vis = bool(pending_refs)

        if not stuck_refs:
            continue
        logger.warning(
            "GSB-%s evaluation reached the retry limit (%d attempts) for refs: %s. "
            "Skipping these refs.",
            channel,
            MAX_GSB_ATTEMPTS,
            ", ".join(stuck_refs),
        )
