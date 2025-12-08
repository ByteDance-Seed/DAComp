#!/usr/bin/env python3

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional
import re

VISUAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".pdf"}
TERMINATE_PREFIX = "terminate("
TERMINATE_PATTERN = re.compile(
    r"terminate\(output=(?P<quote>'''|\"\"\"|'|\")(?P<body>.*)(?P=quote)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_string(value: Optional[str]) -> str:
    return str(value).strip() if value is not None else ""


def _should_include_response(step: dict, response: str) -> bool:  # noqa: ARG001
    """Determine whether a response provides new information."""
    normalized = _normalize_string(response)
    if not normalized:
        return False

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return False

    redundant_prefixes = ("Thought:", "Action:", "Observation:", "Response:")
    if all(any(line.startswith(prefix) for prefix in redundant_prefixes) for line in lines):
        return False

    return True


def format_trajectory(trajectory: Iterable[dict]) -> str:
    """Format an agent trajectory into a human-readable string."""
    if not trajectory:
        return "No trajectory data available."

    lines: list[str] = []
    for idx, step in enumerate(trajectory):
        lines.append(f"--- Step {idx} ---")
        for key in ("thought", "action", "observation"):
            value = step.get(key)
            if value:
                lines.append(f"{key}: {value}")
        response = step.get("response")
        if response and _should_include_response(step, response):
            lines.append(f"response: {response}")
        lines.append("")

    return "\n".join(lines).strip()


def write_text_file(path: Path, content: str) -> None:
    """Write UTF-8 text to a file, ensuring the parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
        if content and not content.endswith("\n"):
            f.write("\n")


def _safe_relative_to(path: Path, start: Path) -> Path:
    try:
        return path.relative_to(start)
    except ValueError:
        return Path(path.name)


def _collect_visual_artifacts(instance_dir: Path, data: dict) -> set[Path]:
    """Collect paths to visual artifacts that should be copied."""
    visual_paths: set[Path] = set()

    for file_path in instance_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in VISUAL_EXTENSIONS:
            visual_paths.add(file_path)

    result_files = data.get("result_files") or {}
    for key in ("added_files", "changed_files", "post_process_files"):
        for file_str in result_files.get(key, []):
            file_path = Path(file_str)
            if file_path.exists() and file_path.suffix.lower() in VISUAL_EXTENSIONS:
                visual_paths.add(file_path)

    return visual_paths


def _copy_visuals(instance_dir: Path, target_dir: Path, data: dict) -> None:
    for file_path in _collect_visual_artifacts(instance_dir, data):
        relative_path = _safe_relative_to(file_path, instance_dir)
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination)


def _strip_wrapping_quotes(text: str) -> str:
    stripped = text.strip()
    for quote in ('"""', "'''", '"', "'"):
        if stripped.startswith(quote) and stripped.endswith(quote) and len(stripped) >= 2 * len(quote):
            return stripped[len(quote) : -len(quote)].strip()
    return stripped


def _strip_terminate_artifacts(text: str) -> str:
    if "Terminate(" not in text and "terminate(" not in text:
        return text

    lower_text = text.lower()
    idx = lower_text.rfind(TERMINATE_PREFIX)
    before = text[:idx].rstrip()
    if before:
        return before

    match = TERMINATE_PATTERN.search(text[idx:])
    if not match:
        return text

    body = match.group("body").strip()
    return body or text


def _clean_answer_text(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""

    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\n", "\n")
    text = _strip_terminate_artifacts(text)
    stripped = _strip_wrapping_quotes(text)

    # Remove dangling leading quotes such as """ that appear without a closing pair.
    for prefix in ('"""', "'''", '"', "'"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].lstrip()
    for suffix in ('"""', "'''", '"', "'"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)].rstrip()

    return stripped


def _extract_response_from_trajectory(trajectory: Iterable[dict]) -> str:
    if not trajectory:
        return ""

    # Prefer the response corresponding to the Terminate action.
    for step in reversed(list(trajectory)):
        action = _normalize_string(step.get("action", ""))
        response = _clean_answer_text(step.get("response"))
        if action.lower().startswith(TERMINATE_PREFIX) and response:
            return response

    # Fall back to the last non-empty response if Terminate is missing or malformed.
    for step in reversed(list(trajectory)):
        response = _clean_answer_text(step.get("response"))
        if response:
            return response

    return ""


REPORT_CANDIDATES = (
    "final_report.md",
    "report.md",
    "analysis.md",
    "employee_analysis_report.md",
    "stage2.md",
)


def _extract_answer(data: dict, instance_dir: Path) -> str:
    """Choose the best available final report text."""
    for name in REPORT_CANDIDATES:
        candidate = instance_dir / name
        if candidate.exists():
            try:
                text = candidate.read_text(encoding="utf-8").strip()
            except Exception as exc:  # noqa: BLE001
                print(f"Warning: failed to read {candidate}: {exc}", file=sys.stderr)
                continue
            if text:
                return text

    for extra in sorted(instance_dir.glob("*.md")):
        if extra.name in REPORT_CANDIDATES:
            continue
        try:
            text = extra.read_text(encoding="utf-8").strip()
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: failed to read {extra}: {exc}", file=sys.stderr)
            continue
        if text:
            return text

    candidates: list[str] = []

    primary_answer = _clean_answer_text(data.get("result"))
    if primary_answer:
        candidates.append(primary_answer)

    trajectory_answer = _extract_response_from_trajectory(data.get("trajectory", []))
    if trajectory_answer:
        candidates.append(trajectory_answer)

    return max(candidates, key=len) if candidates else ""


def process_instance(instance_dir: Path, target_dir: Path) -> Optional[str]:
    """Process a single dacomp instance directory."""
    result_file = instance_dir / "spider" / "result.json"
    if not result_file.exists():
        return f"Skipping {instance_dir.name}: missing spider/result.json"

    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:  # noqa: BLE001
        return f"Failed to read {result_file}: {exc}"

    trajectory = data.get("trajectory", [])
    # Prefer any authored markdown report over fallback response text.
    report_text = _extract_answer(data, instance_dir)
    answer = report_text if report_text else ""
    trajectory_text = format_trajectory(trajectory)

    target_dir.mkdir(parents=True, exist_ok=True)

    trajectory_path = target_dir / f"{instance_dir.name}-traj.txt"
    answer_path = target_dir / f"{instance_dir.name}.md"

    write_text_file(trajectory_path, trajectory_text)
    write_text_file(answer_path, answer)

    _copy_visuals(instance_dir, target_dir, data)

    return None


def generate_visualization_results(
    folder_name: str,
    output_root: Path,
    base_dir: Optional[Path] = None,
) -> None:
    """
    Generate visualization-ready artifacts for a dacomp output folder.

    Args:
        folder_name: Name of the folder inside the agent output directory.
        output_root: Directory under which the visualization folder will be created.
        base_dir: Directory containing dacomp output folders. Defaults to the script's output folder.
    """

    script_dir = Path(__file__).resolve().parent
    base_dir = base_dir or script_dir / "output"

    input_folder = base_dir / folder_name
    if not input_folder.exists():
        raise FileNotFoundError(f"Input folder {input_folder} does not exist.")

    output_root = Path(output_root).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    target_folder = output_root / folder_name
    if target_folder.exists():
        shutil.rmtree(target_folder)
    target_folder.mkdir(parents=True, exist_ok=True)

    skipped_instances: list[str] = []

    for item in sorted(input_folder.iterdir()):
        if not item.is_dir() or not item.name.startswith("dacomp-"):
            continue

        target_instance_dir = target_folder / item.name
        error_message = process_instance(item, target_instance_dir)
        if error_message:
            skipped_instances.append(error_message)

    if skipped_instances:
        for message in skipped_instances:
            print(message)
        print(f"Finished with {len(skipped_instances)} skipped instances.")
    else:
        print(f"Successfully generated visualization results in {target_folder}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export dacomp agent outputs into visualization-friendly folders.",
    )
    parser.add_argument(
        "folder_name",
        help="Name of the output folder (e.g., Doubao-Seed-1.6-thinking-test1).",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=None,
        help=(
            "Directory to store the visualization results. "
            "Defaults to an 'output_vis' folder next to this script."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    default_output_dir = Path(args.output_dir).expanduser() if args.output_dir else script_dir / "output_vis"

    output_root = default_output_dir
    base_dir = script_dir / "output"

    try:
        generate_visualization_results(args.folder_name, output_root, base_dir=base_dir)
    except FileNotFoundError as exc:
        print(exc)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
