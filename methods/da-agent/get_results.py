#!/usr/bin/env python3

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

VISUAL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".pdf"}


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


def _collect_visual_artifacts(instance_dir: Path) -> set[Path]:
    """Collect paths to visual artifacts, preferring the curated images folder."""
    visual_paths: set[Path] = set()
    images_dir = instance_dir / "images"
    search_roots = [images_dir] if images_dir.exists() else [instance_dir]

    for root in search_roots:
        for file_path in root.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in VISUAL_EXTENSIONS:
                visual_paths.add(file_path)
    return visual_paths


def _copy_visuals(instance_dir: Path, target_dir: Path) -> None:
    for file_path in _collect_visual_artifacts(instance_dir):
        relative_path = _safe_relative_to(file_path, instance_dir)
        destination = target_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, destination)


def process_instance(instance_dir: Path, target_dir: Path) -> Optional[str]:
    """Process a single da-agent instance directory."""
    final_report = instance_dir / "final_result.md"
    stage1_file = instance_dir / "da_agent" / "result.json"

    if not final_report.exists() and not stage1_file.exists():
        return f"Skipping {instance_dir.name}: missing final_result.md and da_agent/result.json"

    answer = final_report.read_text(encoding="utf-8") if final_report.exists() else ""
    trajectory_text = ""

    if stage1_file.exists():
        try:
            with open(stage1_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001
            return f"Failed to read {stage1_file}: {exc}"

        trajectory_text = format_trajectory(data.get("trajectory", []))

        if not answer:
            answer = data.get("result", "")
            if isinstance(answer, str):
                answer = answer.replace("\\n", "\n")

    target_dir.mkdir(parents=True, exist_ok=True)

    trajectory_path = target_dir / f"{instance_dir.name}-traj.txt"
    answer_path = target_dir / f"{instance_dir.name}.md"

    write_text_file(trajectory_path, trajectory_text)
    write_text_file(answer_path, answer)

    _copy_visuals(instance_dir, target_dir)

    return None


def generate_visualization_results(
    folder_name: str,
    output_root: Path,
    base_dir: Optional[Path] = None,
) -> None:
    """
    Generate visualization-ready artifacts for a da-agent output folder.

    Args:
        folder_name: Name of the folder inside the agent output directory.
        output_root: Directory under which the visualization folder will be created.
        base_dir: Directory containing da-agent output folders. Defaults to the script's output folder.
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
        description="Export da-agent outputs into visualization-friendly folders.",
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
