from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from core.rubric_scoring import (
    DEFAULT_INSTANCE_RANGE,
    LANGUAGE_CONFIG,
    compute_file_score,
    load_metadata_scores,
    run_for_language,
)

ScoreStats = Optional[Tuple[Optional[float], int]]
Record = Dict[str, Union[str, int, float, None]]


def _extract_average(stats: ScoreStats, multiplier: float = 1.0) -> Optional[float]:
    if not stats:
        return None
    value, _ = stats
    if value is None:
        return None
    return round(value * multiplier, 2)


def _extract_count(result: Dict[str, ScoreStats]) -> int:
    for key in (
        "weighted_total",
        "rubrics",
        "gsb_readability",
        "gsb_professionalism",
        "gsb_visualization",
        "rubric_completeness",
        "rubric_accuracy",
        "rubric_conclusiveness",
    ):
        stats = result.get(key)
        if stats and stats[1]:
            return int(stats[1])
    return 0


def write_overall_results(language: str) -> None:
    language = language.lower()
    if language not in LANGUAGE_CONFIG:
        raise ValueError(f"Unsupported language: {language}")

    lang_cfg = LANGUAGE_CONFIG[language]
    base_dir = Path(__file__).resolve().parent
    scores_dir = base_dir / lang_cfg["scores"]
    src_dir = base_dir / lang_cfg["src"]
    if not src_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")
    if not scores_dir.exists():
        raise FileNotFoundError(f"Scores directory not found: {scores_dir}")

    metadata_map = load_metadata_scores([src_dir])
    if not metadata_map:
        raise RuntimeError("Failed to load metadata for overall scoring.")

    prefix = lang_cfg["instance_prefix"]
    instance_filter = {f"{prefix}-{idx:03d}" for idx in DEFAULT_INSTANCE_RANGE}

    records: List[Record] = []
    for csv_path in sorted(scores_dir.glob("*.csv")):
        if csv_path.name == "overall_results.csv":
            continue
        result = compute_file_score(csv_path, metadata_map, instance_filter)
        record: Record = {
            "name": csv_path.name,
            "count": _extract_count(result),
            "completeness": _extract_average(result.get("rubric_completeness")),
            "accuracy": _extract_average(result.get("rubric_accuracy")),
            "conclusiveness": _extract_average(result.get("rubric_conclusiveness")),
            "readability": _extract_average(
                result.get("gsb_readability"), multiplier=100.0
            ),
            "professionalism": _extract_average(
                result.get("gsb_professionalism"), multiplier=100.0
            ),
            "visualization": _extract_average(
                result.get("gsb_visualization"), multiplier=100.0
            ),
            "total": _extract_average(result.get("weighted_total")),
        }
        records.append(record)

    output_path = scores_dir / "overall_results.csv"
    fieldnames: List[str] = [
        "name",
        "count",
        "completeness",
        "accuracy",
        "conclusiveness",
        "readability",
        "professionalism",
        "visualization",
        "total",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score Chinese DACOMP reports.")
    default_scores = LANGUAGE_CONFIG["zh"]["scores"]
    default_src = LANGUAGE_CONFIG["zh"]["src"]
    parser.add_argument(
        "--scores-dir",
        "--score-dir",
        "--score_dir",
        dest="scores_dir",
        default=default_scores,
        help="覆盖默认模型得分 CSV 所在目录（默认：LANGUAGE_CONFIG 中的 model_scores_zh）。",
    )
    parser.add_argument(
        "--src-dir",
        "--src_dir",
        dest="src_dir",
        default=default_src,
        help="覆盖默认的任务源数据目录（默认：LANGUAGE_CONFIG 中的 src_zh）。",
    )
    return parser.parse_args()


def _override_language_paths(scores_dir: Optional[str], src_dir: Optional[str]) -> None:
    if not scores_dir and not src_dir:
        return
    lang_cfg = LANGUAGE_CONFIG["zh"]
    if src_dir:
        lang_cfg["src"] = str(Path(src_dir))
    if scores_dir:
        lang_cfg["scores"] = str(Path(scores_dir))


def main() -> None:
    args = _parse_args()
    _override_language_paths(args.scores_dir, args.src_dir)
    run_for_language("zh")
    write_overall_results("zh")


if __name__ == "__main__":
    main()
