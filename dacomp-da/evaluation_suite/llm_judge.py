from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set

from loguru import logger

try:
    from core.pipeline import evaluate_models
    from core.tasks import (
        is_valid_gsb_response,
        is_valid_rubrics_response,
    )
except ImportError:  # pragma: no cover
    current_dir = Path(__file__).resolve().parent
    if str(current_dir) not in sys.path:
        sys.path.append(str(current_dir))
    from core.pipeline import evaluate_models  # type: ignore  # noqa: E402
    from core.tasks import (  # type: ignore  # noqa: E402
        is_valid_gsb_response,
        is_valid_rubrics_response,
    )


DEFAULT_METADATA_ROOT = Path(__file__).resolve().parent / "src_zh"
DEFAULT_AGENT_RESULTS_ROOT = Path(__file__).resolve().parent / "agent_results"
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LANGUAGE_METADATA = {
    "zh": DEFAULT_METADATA_ROOT,
    "en": DEFAULT_METADATA_ROOT.parent / "src",
}
LANGUAGE_OUTPUT_DIR = {
    "zh": "model_scores_zh",
    "en": "model_scores",
}
MAX_RERUN_ROUNDS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DACOMP evaluation for raw agent_results directories or prepared JSONL files.",
    )
    parser.add_argument(
        "--inputs",
        nargs="*",
        help=(
            "Paths to agent_results model directories or JSONL files. "
            "Defaults to all model folders under --inputs-dir."
        ),
    )
    parser.add_argument(
        "--metadata-root",
        default=None,
        help="Path to metadata directory (per-instance rubric/gsb refs). Defaults to evaluation_suite/src_zh.",
    )
    parser.add_argument(
        "--rubrics-model",
        required=True,
        help="Model config name for rubrics evaluation (required).",
    )
    parser.add_argument(
        "--gsb-model-text",
        required=True,
        help="Model config for GSB readability/professionalism evaluation (required).",
    )
    parser.add_argument(
        "--gsb-model-vis",
        required=True,
        help="Model config for GSB visualization evaluation (required).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to store evaluation csv files.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Thread pool size for LLM calls.",
    )
    parser.add_argument(
        "--inputs-dir",
        type=Path,
        default=DEFAULT_AGENT_RESULTS_ROOT,
        help="Directory containing agent_results model folders (default: evaluation_suite/agent_results).",
    )
    parser.add_argument(
        "--language",
        choices=["zh", "en"],
        default="en",
        help="Metadata/output language shortcut (sets default metadata/output dirs).",
    )
    return parser.parse_args()


def discover_inputs(
    provided: Optional[Sequence[str]],
    inputs_dir: Path,
) -> List[Path]:
    if provided:
        return [Path(item).expanduser() for item in provided]

    root = inputs_dir.expanduser()
    if not root.exists():
        logger.warning(f"Default inputs directory does not exist: {root}")
        return []

    candidates = sorted(root.iterdir())
    if not candidates:
        logger.warning(f"No model folders found under {root}")
    return candidates


def read_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def collect_instances(model_dir: Path) -> Iterable[dict]:
    for instance_dir in sorted(p for p in model_dir.iterdir() if p.is_dir()):
        instance_id = instance_dir.name
        traj_path = instance_dir / f"{instance_id}-traj.txt"
        answer_path = instance_dir / f"{instance_id}.md"

        try:
            trajectory = read_text_file(traj_path)
        except FileNotFoundError as exc:
            logger.warning(str(exc))
            continue

        try:
            answer = read_text_file(answer_path)
        except FileNotFoundError as exc:
            logger.warning(str(exc))
            continue

        image_paths: List[str] = []
        for match in IMAGE_PATTERN.findall(answer):
            candidate = (instance_dir / match).resolve()
            if candidate.exists():
                image_paths.append(str(candidate))

        yield {
            "instance_id": instance_id,
            "trajectory": trajectory,
            "answer": answer,
            "answer_path": str(answer_path),
            "trajectory_path": str(traj_path),
            "answer_images": image_paths,
        }


def is_model_directory(path: Path) -> bool:
    if not path.is_dir():
        return False
    for child in path.iterdir():
        if not child.is_dir():
            continue
        marker = child / f"{child.name}.md"
        traj = child / f"{child.name}-traj.txt"
        if marker.exists() or traj.exists():
            return True
    return False


def convert_agent_directory(model_dir: Path, output_root: Path) -> Optional[Path]:
    records = list(collect_instances(model_dir))
    if not records:
        logger.warning(f"No valid instances found in {model_dir}")
        return None
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{model_dir.name}.jsonl"
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            json.dump(record, handle, ensure_ascii=False)
            handle.write("\n")
    logger.info(f"Prepared {len(records)} instances from {model_dir} -> {output_path}")
    return output_path


def prepare_model_inputs(
    inputs: Sequence[Path],
    temp_root: Path,
) -> List[Path]:
    model_files: List[Path] = []
    for raw_path in inputs:
        path = raw_path.expanduser()
        if not path.exists():
            logger.warning(f"Input path does not exist: {path}")
            continue

        if path.is_file():
            if path.suffix.lower() == ".jsonl":
                model_files.append(path)
            else:
                logger.warning(f"Unsupported file type (expected .jsonl): {path}")
            continue

        if path.is_dir():
            if is_model_directory(path):
                converted = convert_agent_directory(path, temp_root)
                if converted:
                    model_files.append(converted)
                continue

            model_dirs = [
                candidate
                for candidate in sorted(path.iterdir())
                if is_model_directory(candidate)
            ]
            if not model_dirs:
                logger.warning(f"No model directories found under {path}")
                continue
            for model_dir in model_dirs:
                converted = convert_agent_directory(model_dir, temp_root)
                if converted:
                    model_files.append(converted)
            continue

        logger.warning(f"Unsupported input path: {path}")

    return model_files


def prune_invalid_rows(csv_path: Path) -> Set[str]:
    invalid_instances: Set[str] = set()
    if not csv_path.exists():
        return invalid_instances
    fieldnames: List[str] = []
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Failed to read evaluation output {csv_path}: {exc}")
        return invalid_instances

    if not rows:
        return invalid_instances

    valid_rows: List[dict] = []
    if not fieldnames:
        fieldnames = list(rows[0].keys())

    for row in rows:
        instance_id = row.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id.strip():
            continue
        invalid = False
        rubrics_raw = row.get("rubrics_result") or ""
        if rubrics_raw.strip() and not is_valid_rubrics_response(rubrics_raw):
            invalid = True

        def _validate_gsb_column(raw_value: str) -> bool:
            if not raw_value.strip():
                return True
            try:
                payload = json.loads(raw_value)
            except json.JSONDecodeError:
                return False
            if not isinstance(payload, dict):
                return False
            for content in payload.values():
                if not (isinstance(content, str) and content.strip()):
                    return False
                if not is_valid_gsb_response(content):
                    return False
            return True

        if not invalid:
            text_raw = row.get("gsb_text_results") or row.get("gsb_results") or ""
            if text_raw.strip() and not _validate_gsb_column(text_raw):
                invalid = True
        if not invalid:
            vis_raw = row.get("gsb_vis_results") or ""
            if vis_raw.strip() and not _validate_gsb_column(vis_raw):
                invalid = True
        if invalid:
            invalid_instances.add(instance_id)
            continue
        valid_rows.append(row)

    if invalid_instances:
        logger.warning(
            "Detected {} invalid rows in {}. Removing before rerun.",
            len(invalid_instances),
            csv_path.name,
        )
        if valid_rows:
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(valid_rows)
        else:
            csv_path.unlink(missing_ok=True)
    return invalid_instances


def main() -> None:
    args = parse_args()
    language = args.language.lower()
    metadata_default = LANGUAGE_METADATA.get(language, DEFAULT_METADATA_ROOT)
    output_default = LANGUAGE_OUTPUT_DIR.get(language, "model_scores_zh")
    input_candidates = discover_inputs(
        provided=args.inputs,
        inputs_dir=args.inputs_dir,
    )

    if args.metadata_root:
        metadata_source = Path(args.metadata_root).expanduser()
    else:
        metadata_source = metadata_default
    logger.info(f"Using metadata from {metadata_source}")

    rubrics_model = args.rubrics_model
    gsb_model_text = args.gsb_model_text
    gsb_model_vis = args.gsb_model_vis

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        model_files = prepare_model_inputs(input_candidates, temp_root)
        if not model_files:
            logger.warning("No valid model inputs found, nothing to evaluate.")
            return

        if args.output_dir:
            output_dir = Path(args.output_dir).expanduser()
        else:
            output_dir = Path(output_default).expanduser()

        pending_files = list(model_files)
        rerun_round = 0
        while pending_files:
            result_paths = evaluate_models(
                model_files=pending_files,
                metadata_source=metadata_source,
                rubrics_model=rubrics_model,
                gsb_model_text=gsb_model_text,
                gsb_model_vis=gsb_model_vis,
                output_dir=output_dir,
                max_workers=args.max_workers,
                language=language,
            )
            rerun_targets: List[Path] = []
            for model_file, csv_path in zip(pending_files, result_paths):
                invalid_rows = prune_invalid_rows(csv_path)
                if invalid_rows:
                    rerun_targets.append(model_file)
            if not rerun_targets:
                break
            rerun_round += 1
            if rerun_round >= MAX_RERUN_ROUNDS:
                raise RuntimeError(
                    "Exceeded rerun limit because some responses never produced valid JSON."
                )
            logger.info(
                "Scheduling rerun round {} for {} model(s) due to invalid outputs.",
                rerun_round,
                len(rerun_targets),
            )
            pending_files = rerun_targets


if __name__ == "__main__":
    main()
