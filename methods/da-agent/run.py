import argparse
import copy
import datetime
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from da_agent.envs import DAAgentEnv
from da_agent.agent.agents import PromptAgent
from da_agent.agent.models import call_llm
from da_agent.agent.prompts import (
    DACOMP_STAGE3_SYSTEM_PROMPT_EN,
    DACOMP_STAGE3_SYSTEM_PROMPT_ZH,
)


VISUAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".pdf"}


logger = logging.getLogger("da_agent")
logger.setLevel(logging.DEBUG)

datetime_str: str = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")
file_handler = logging.FileHandler(os.path.join("logs", f"normal-{datetime_str}.log"), encoding="utf-8")
debug_handler = logging.FileHandler(os.path.join("logs", f"debug-{datetime_str}.log"), encoding="utf-8")
stdout_handler = logging.StreamHandler(sys.stdout)
sdebug_handler = logging.FileHandler(os.path.join("logs", f"sdebug-{datetime_str}.log"), encoding="utf-8")

file_handler.setLevel(logging.INFO)
debug_handler.setLevel(logging.DEBUG)
stdout_handler.setLevel(logging.INFO)
sdebug_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="\x1b[1;33m[%(asctime)s \x1b[31m%(levelname)s \x1b[32m%(module)s/%(lineno)d-%(processName)s\x1b[1;33m] \x1b[0m%(message)s"
)
for handler in (file_handler, debug_handler, stdout_handler, sdebug_handler):
    handler.setFormatter(formatter)

stdout_handler.addFilter(logging.Filter("da_agent"))
sdebug_handler.addFilter(logging.Filter("da_agent"))

logger.addHandler(file_handler)
logger.addHandler(debug_handler)
logger.addHandler(stdout_handler)
logger.addHandler(sdebug_handler)


def config() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Three-stage DACOMP agent runner")
    parser.add_argument("--max_steps", type=int, default=120)
    parser.add_argument("--max_memory_length", type=int, default=31)
    parser.add_argument("--suffix", "-s", type=str, default="test1")

    parser.add_argument("--model", type=str, default="gpt-4o")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top_p", type=float, default=1.0)
    parser.add_argument("--max_tokens", type=int, default=16384)

    parser.add_argument("--test_path", "-t", type=str, default="../../dacomp-da/tasks/dacomp-da.jsonl")
    parser.add_argument("--example_index", "-i", type=str, default="all")
    parser.add_argument("--example_name", "-n", type=str, default="")
    parser.add_argument("--overwriting", action="store_true", default=False)
    parser.add_argument("--retry_failed", action="store_true", default=False)

    parser.add_argument("--output_dir", type=str, default="output")
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--dbt_only", action="store_true", default=True)
    parser.add_argument("--language", choices=["zh", "en"], default="en")

    parser.add_argument(
        "--type",
        "-k",
        type=str,
        default="all",
        help="Filter tasks by type: 'c' creation, 'e' evolution, 'd' design, 'ce' combination, or 'all'",
    )

    # kept for CLI parity, stage2 always uses multimodal prompts
    parser.add_argument("--image_prompt", action="store_true", help=argparse.SUPPRESS)

    return parser.parse_args()


def load_task_configs(args: argparse.Namespace) -> List[Dict]:
    path = Path(args.test_path)
    assert path.exists() and path.suffix == ".jsonl", f"Invalid test_path, must be jsonl: {path}"
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def filter_task_configs(task_configs: List[Dict], args: argparse.Namespace) -> List[Dict]:
    if args.type != "all":
        task_type_map = {"c": "creation", "e": "evolution", "d": "design"}
        target_types = []
        for char in args.type:
            mapped = task_type_map.get(char)
            if not mapped:
                raise ValueError(f"Invalid task type flag {char}")
            target_types.append(mapped)
        task_configs = [task for task in task_configs if task.get("type") in target_types]
        logger.info("Filtered to %d tasks for types: %s", len(task_configs), ", ".join(target_types))

    if args.example_name:
        task_configs = [task for task in task_configs if args.example_name in task["id"]]
    elif args.example_index != "all":
        if "-" in args.example_index:
            start, end = map(int, args.example_index.split("-"))
            task_configs = task_configs[start:end]
        else:
            indices = list(map(int, args.example_index.split(",")))
            task_configs = [task_configs[i] for i in indices]
    return task_configs


def build_stage_task_config(stage_label: str, task_config: Dict, source_dir: Path, instance_root: Path) -> Dict:
    config = copy.deepcopy(task_config)
    task_data_dir = source_dir / task_config["instance_id"]
    config_steps = [
        {
            "type": "copy_all_subfiles",
            "parameters": {"dirs": [str(task_data_dir)]},
        }
    ]
    config["config"] = config_steps
    return config


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = (content or "").replace("\\n", "\n")
    path.write_text(normalized, encoding="utf-8")


def run_stage(
    *,
    stage_label: str,
    instance_root: Path,
    args: argparse.Namespace,
    experiment_id: str,
    task_config: Dict,
    source_dir: Path,
    use_image_prompt: bool,
) -> Tuple[str, Dict, Path]:
    stage_dir = instance_root / f"{stage_label}_env"
    ensure_clean_dir(stage_dir)

    env_config = {
        "init_args": {
            "name": f"{experiment_id}-{task_config['instance_id']}-{stage_label}",
            "work_dir": "/workspace",
            "language": args.language,
        }
    }
    stage_task_config = build_stage_task_config(stage_label, task_config, source_dir, instance_root)
    env = DAAgentEnv(
        env_config=env_config,
        task_config=stage_task_config,
        cache_dir="./cache",
        mnt_dir=str(stage_dir),
    )

    agent = PromptAgent(
        model=args.model,
        max_tokens=args.max_tokens,
        top_p=args.top_p,
        temperature=args.temperature,
        max_memory_length=args.max_memory_length,
        max_steps=args.max_steps,
        use_plan=args.plan,
        use_image_prompt=use_image_prompt,
        language=args.language,
    )
    agent.set_env_and_task(env)
    logger.info("[%s] Starting stage %s", task_config["instance_id"], stage_label)
    done, result_output = agent.run()
    trajectory = agent.get_trajectory()

    result_files = env.post_process()
    env.close()

    stage_payload = {
        "finished": done,
        "steps": len(trajectory.get("trajectory", [])),
        "result": result_output,
        "result_files": result_files,
        **trajectory,
    }

    da_dir = stage_dir / "da_agent"
    da_dir.mkdir(parents=True, exist_ok=True)
    with (da_dir / "result.json").open("w", encoding="utf-8") as f:
        json.dump(stage_payload, f, indent=2, ensure_ascii=False)

    logger.info("[%s] Stage %s finished=%s", task_config["instance_id"], stage_label, done)
    return result_output or "", stage_payload, stage_dir


def parse_image_refs(markdown_text: str) -> Dict[str, str]:
    if not markdown_text:
        return {}
    pattern = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)")
    refs: Dict[str, str] = {}
    for match in pattern.finditer(markdown_text):
        raw_path = match.group("path").strip()
        filename = os.path.basename(raw_path.split("?")[0])
        if not filename:
            continue
        refs[filename] = match.group("alt").strip() or filename
    return refs


def collect_stage2_images(
    stage_dir: Path, stage_payload: Dict, stage2_report: str, instance_root: Path
) -> List[Dict[str, str]]:
    references = parse_image_refs(stage2_report)
    images_dir = instance_root / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    metadata: List[Dict[str, str]] = []
    used_names: set = set()

    def register_file(file_path: Path):
        if not file_path.exists() or file_path.suffix.lower() not in VISUAL_EXTENSIONS:
            return
        new_name = file_path.name
        stem = file_path.stem
        suffix = file_path.suffix
        counter = 1
        while new_name in used_names:
            new_name = f"{stem}_{counter}{suffix}"
            counter += 1
        used_names.add(new_name)
        target = images_dir / new_name
        shutil.copy2(file_path, target)
        metadata.append(
            {
                "source": str(file_path),
                "filename": new_name,
                "relative_path": f"images/{new_name}",
                "alt": references.get(file_path.name) or references.get(new_name) or new_name,
            }
        )

    result_files = stage_payload.get("result_files") or {}
    for key in ("added_files", "changed_files", "post_process_files"):
        for raw_path in result_files.get(key, []):
            path = Path(raw_path)
            if not path.is_absolute():
                path = stage_dir / raw_path
            register_file(path)

    return metadata


def get_stage3_system_prompt(language: str) -> str:
    return DACOMP_STAGE3_SYSTEM_PROMPT_EN if language == "en" else DACOMP_STAGE3_SYSTEM_PROMPT_ZH


def synthesize_final_report(
    *,
    args: argparse.Namespace,
    stage1_path: Path,
    stage2_path: Path,
    images: List[Dict[str, str]],
    final_path: Path,
    stage1_fallback: str = "",
    stage2_fallback: str = "",
) -> Tuple[str, Dict]:
    stage1_text = stage1_path.read_text(encoding="utf-8") if stage1_path.exists() else ""
    if not stage1_text.strip():
        fallback_stage1 = stage1_path.parent / "stage1_env" / "stage1.md"
        if fallback_stage1.exists():
            stage1_text = fallback_stage1.read_text(encoding="utf-8")
    if not stage1_text.strip() and stage1_fallback.strip():
        logger.warning(
            "Stage1 markdown missing on disk; using fallback content from runtime output."
        )
        stage1_text = stage1_fallback.strip()
    stage2_text = stage2_path.read_text(encoding="utf-8") if stage2_path.exists() else ""
    if not stage2_text.strip():
        fallback_stage2 = stage2_path.parent / "stage2_env" / "stage2.md"
        if fallback_stage2.exists():
            stage2_text = fallback_stage2.read_text(encoding="utf-8")
    if not stage2_text.strip() and stage2_fallback.strip():
        logger.warning(
            "Stage2 markdown missing on disk; using fallback content from runtime output."
        )
        stage2_text = stage2_fallback.strip()

    if not stage1_text.strip():
        raise RuntimeError("Stage1 report missing; cannot synthesize final result.")

    image_lines = (
        "\n".join(
            f"- {img['relative_path']}: alt='{img['alt']}' (source: {os.path.basename(img['source'])})"
            for img in images
        )
        if images
        else "No images captured during stage2."
    )

    system_prompt = get_stage3_system_prompt(args.language)
    stage3_instruction = (
        "Use Stage1 as the backbone, insert the listed images with English captions, and return the final_result.md strictly in English."
        if args.language == "en"
        else "请以 Stage1 为骨架插入上述图片引用，并返回最终 final_result.md。"
    )

    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Stage1 Markdown:\n" + stage1_text},
                    {
                        "type": "text",
                        "text": "Stage2 Markdown (includes chart references):\n"
                        + (stage2_text or "Stage2 did not return additional commentary."),
                    },
                    {
                        "type": "text",
                        "text": "Image assets:\n"
                        + image_lines
                        + f"\n{stage3_instruction}",
                    },
                ],
            },
        ],
        "max_tokens": args.max_tokens,
        "top_p": args.top_p,
    }
    if args.temperature is not None:
        payload["temperature"] = args.temperature

    success, response = call_llm(payload)
    if not success:
        raise RuntimeError(f"Stage3 LLM call failed: {response}")

    normalized = (response or "").replace("\\n", "\n").strip()
    stage3_record = {
        "system_prompt": system_prompt,
        "stage1_md": stage1_text,
        "stage2_md": stage2_text,
        "images": images,
        "response": normalized,
    }

    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_text(normalized, encoding="utf-8")
    logger.info("Final report saved to %s", final_path)
    return normalized, stage3_record


def should_skip_instance(result_path: Path, args: argparse.Namespace) -> bool:
    if not result_path.exists():
        return False
    if args.overwriting:
        return False
    if not args.retry_failed:
        return True
    try:
        with result_path.open("r", encoding="utf-8") as f:
            result = json.load(f)
    except Exception:
        return False
    final_report = result.get("final_report_path")
    final_finished = Path(final_report).exists() if final_report else False
    final_text = Path(final_report).read_text(encoding="utf-8").lower() if final_finished else ""
    if final_finished and "fail" not in final_text:
        return True
    return False


def test(args: argparse.Namespace) -> None:
    logger.info("Args: %s", args)
    experiment_suffix = args.suffix or "default"
    experiment_id = args.model.split("/")[-1] + "-" + experiment_suffix
    if args.plan:
        experiment_id = f"{experiment_id}-plan"

    tasks = filter_task_configs(load_task_configs(args), args)
    source_dir = Path(args.test_path).resolve().parent

    for task_config in tasks:
        instance_root = Path(args.output_dir) / experiment_id / task_config["instance_id"]
        final_summary_path = instance_root / "da_agent" / "final_summary.json"

        if should_skip_instance(final_summary_path, args):
            logger.info("Skipping %s", instance_root)
            continue
        if final_summary_path.exists():
            logger.info("Overwriting %s", instance_root)
            shutil.rmtree(instance_root, ignore_errors=True)

        instance_root.mkdir(parents=True, exist_ok=True)

        stage1_text: str = ""
        stage2_text: str = ""
        stage1_payload: Dict = {}
        stage2_payload: Dict = {}
        stage3_payload: Dict = {}
        stage1_dir = instance_root / "stage1_env"
        stage2_dir = instance_root / "stage2_env"

        try:
            stage1_text, stage1_payload, stage1_dir = run_stage(
                stage_label="stage1",
                instance_root=instance_root,
                args=args,
                experiment_id=experiment_id,
                task_config=task_config,
                source_dir=source_dir,
                use_image_prompt=False,
            )
            stage1_md = instance_root / "stage1.md"
            stage1_md_source = stage1_dir / "stage1.md"
            if stage1_md_source.exists():
                stage1_md.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stage1_md_source, stage1_md)
            else:
                write_text_file(stage1_md, stage1_text)
            stage1_result_file = stage1_dir / "da_agent" / "result.json"
            da_dir = instance_root / "da_agent"
            da_dir.mkdir(parents=True, exist_ok=True)
            if stage1_result_file.exists():
                shutil.copy2(stage1_result_file, da_dir / "result.json")

            stage2_text, stage2_payload, stage2_dir = run_stage(
                stage_label="stage2",
                instance_root=instance_root,
                args=args,
                experiment_id=experiment_id,
                task_config=task_config,
                source_dir=source_dir,
                use_image_prompt=True,
            )
            stage2_md = instance_root / "stage2.md"
            stage2_md_source = stage2_dir / "stage2.md"
            if stage2_md_source.exists():
                stage2_md.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(stage2_md_source, stage2_md)
            else:
                write_text_file(stage2_md, stage2_text)

            stage2_images = collect_stage2_images(stage2_dir, stage2_payload, stage2_text, instance_root)

            stage3_dir = instance_root / "stage3_env"
            ensure_clean_dir(stage3_dir)
            final_path = instance_root / "final_result.md"
            final_text, stage3_payload = synthesize_final_report(
                args=args,
                stage1_path=stage1_md,
                stage2_path=stage2_md,
                images=stage2_images,
                final_path=final_path,
                stage1_fallback=stage1_text,
                stage2_fallback=stage2_text,
            )
            stage3_result_dir = stage3_dir / "da_agent"
            stage3_result_dir.mkdir(parents=True, exist_ok=True)
            with (stage3_result_dir / "result.json").open("w", encoding="utf-8") as f:
                json.dump(stage3_payload, f, indent=2, ensure_ascii=False)

            summary = {
                "task_id": task_config["instance_id"],
                "stage1": stage1_payload,
                "stage2": stage2_payload,
                "stage3": stage3_payload,
                "images": stage2_images,
                "final_report_path": str(final_path),
                "final_report_preview": final_text[:5000],
            }
            final_summary_path.parent.mkdir(parents=True, exist_ok=True)
            with final_summary_path.open("w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            logger.info("Finished %s", task_config["instance_id"])
        except Exception as exc:
            logger.error(
                "Instance %s failed: %s", task_config["instance_id"], exc, exc_info=True
            )
            failure_summary = {
                "task_id": task_config["instance_id"],
                "error": str(exc),
                "stage1": stage1_payload or {"finished": False},
                "stage2": stage2_payload or {"finished": False},
                "stage3": stage3_payload or {},
                "stage1_text": stage1_text,
                "stage2_text": stage2_text,
            }
            final_summary_path.parent.mkdir(parents=True, exist_ok=True)
            with final_summary_path.open("w", encoding="utf-8") as f:
                json.dump(failure_summary, f, indent=2, ensure_ascii=False)
            logger.info(
                "Recorded failure for %s and continuing to the next instance.",
                task_config["instance_id"],
            )
            continue


if __name__ == "__main__":
    test(config())
