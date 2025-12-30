from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd
from loguru import logger

from .pipeline import extract_total_score

DEFAULT_INSTANCE_RANGE = range(1, 101)
LANGUAGE_CONFIG = {
    "zh": {
        "src": "src_zh",
        "scores": "model_scores_zh",
        "instance_prefix": "dacomp-zh",
    },
    "en": {
        "src": "src",
        "scores": "model_scores",
        "instance_prefix": "dacomp",
    },
}


def load_metadata_scores(root_dirs: Iterable[Path]) -> dict[str, dict[str, int]]:
    metadata: dict[str, dict[str, int]] = {}
    for root in root_dirs:
        if not root or not root.exists():
            continue
        for task_dir in sorted(root.iterdir()):
            if not task_dir.is_dir():
                continue
            meta_path = task_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                logger.warning("Failed to parse metadata for {}", task_dir.name)
                continue
            try:
                total = int(payload.get("Total"))
                completeness = int(payload.get("Completeness"))
                accuracy = int(payload.get("Accuracy"))
                conclusiveness = int(payload.get("Conclusiveness"))
            except (TypeError, ValueError):
                logger.warning("Invalid numeric values in metadata for {}", task_dir.name)
                continue
            metadata[task_dir.name] = {
                "Total": total,
                "Completeness": completeness,
                "Accuracy": accuracy,
                "Conclusiveness": conclusiveness,
            }
    return metadata


DIMENSION_LABELS = ("Completeness", "Accuracy", "Conclusiveness")

GSB_READABILITY_KEYS = (
    "可读性",
    "可读性评分",
    "报告结构与可读性",
    "Readability",
    "Readability Score",
    "Structure & Readability",
)
GSB_PROFESSIONALISM_KEYS = (
    "分析专业深度",
    "分析专业有深度",
    "分析专业性",
    "分析专业",
    "Analytical Depth",
    "Analytical Professionalism",
    "Analysis Professionalism",
    "Analysis Depth",
)
GSB_VISUALIZATION_KEYS = (
    "洞察呈现与可视化",
    "洞察呈现",
    "可视化表现",
    "洞察呈现",
    "Insight Presentation & Visualization",
    "Insight Presentation",
    "Visualization",
    "Visualizations",
)
GSB_SCORE_FIELDS = ("得分", "score")


def normalize_dimension_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    if "完备" in raw or "completeness" in text or "complete" in text:
        return "Completeness"
    if "精确" in raw or "准确" in raw or "accuracy" in text or "precis" in text:
        return "Accuracy"
    if "结论" in raw or "conclus" in text or "insight" in text:
        return "Conclusiveness"
    return None


def parse_rubric_dimension_scores(raw_text: Optional[str]) -> Dict[str, float]:
    scores = {label: 0.0 for label in DIMENSION_LABELS}
    if not raw_text or not isinstance(raw_text, str):
        return scores
    text = raw_text.strip()
    if not text:
        return scores
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    else:
        block = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if block:
            text = block.group(1)
    try:
        data = json.loads(text)
    except Exception:
        return scores

    def traverse(obj: Any) -> None:
        if isinstance(obj, dict):
            dim = None
            for key in ("标准类型", "criterion_type", "type", "dimension"):
                if key in obj:
                    dim = normalize_dimension_name(obj.get(key))
                    if dim:
                        break
            if dim:
                value = None
                for key in ("得分", "score"):
                    if key in obj:
                        value = to_optional_float(obj.get(key))
                        if value is not None:
                            break
                if value is not None:
                    scores[dim] += value
            for child in obj.values():
                traverse(child)
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)

    traverse(data)
    return scores


def trans_gsb_score(score_list: Iterable[Optional[float]]) -> Optional[float]:
    POS_THRESHOLD = 3.0

    def score_map(raw: float) -> float:
        if raw < -POS_THRESHOLD:
            return -1.0
        if raw <= POS_THRESHOLD:
            return 0.0
        return 1.0

    mapped: list[float] = []
    for value in score_list:
        if value is None:
            continue
        mapped.append(score_map(float(value)))
    if not mapped:
        return None
    avg = sum(mapped) / len(mapped)
    return max(0.0, avg)


def sanitize(value: Optional[str]) -> str:
    if not value:
        return "none"
    safe: list[str] = []
    for ch in value:
        safe.append(ch if ch.isalnum() or ch in "-_" else "-")
    return "".join(safe)


def to_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):  # type: ignore[arg-type]
            return None
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _scan_pattern(keys: Iterable[str], text: str) -> Optional[float]:
    if not keys:
        return None
    pattern = re.compile(
        "|".join(
            rf"{re.escape(key)}[^\d-]*(-?\d+(?:\.\d+)?)"
            for key in keys
            if key
        ),
        flags=re.IGNORECASE,
    )
    matches = pattern.findall(text)
    if not matches:
        return None
    for match in reversed(matches):
        if isinstance(match, tuple):
            for item in reversed(match):
                if item:
                    try:
                        return float(item)
                    except ValueError:
                        continue
        else:
            try:
                return float(match)
            except ValueError:
                continue
    return None


def extract_gsb_scores(result: str) -> Dict[str, Optional[float]]:
    text = result.strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]
    else:
        block = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if block:
            text = block.group(1)

    data: Optional[Dict[str, Any]] = None
    try:
        candidate = json.loads(text)
        if isinstance(candidate, dict):
            data = candidate
    except Exception:
        cleaned = re.sub(r":\s*\+(\d+(?:\.\d+)?)", r": \1", text)
        cleaned = re.sub(r"\\(?![\"\\/bfnrtu0-9])", r"\\\\", cleaned)
        try:
            candidate = json.loads(cleaned)
            if isinstance(candidate, dict):
                data = candidate
        except Exception:
            logger.debug("Failed to parse GSB result JSON.")

    def lookup_score(keys: Iterable[str]) -> Optional[float]:
        if data:
            for key in keys:
                value = data.get(key)
                if isinstance(value, dict):
                    score = None
                    for field_key in GSB_SCORE_FIELDS:
                        if field_key in value:
                            score = to_optional_float(value.get(field_key))
                            if score is not None:
                                break
                    if score is not None:
                        return score
                else:
                    score = to_optional_float(value)
                    if score is not None:
                        return score
        fallback = _scan_pattern(keys, text)
        if fallback is not None:
            return fallback
        return -10.0

    readability = lookup_score(GSB_READABILITY_KEYS)
    professionalism = lookup_score(GSB_PROFESSIONALISM_KEYS)
    visualization = lookup_score(GSB_VISUALIZATION_KEYS)

    total: Optional[float] = None
    if data and "总得分" in data:
        total = to_optional_float(data.get("总得分"))
    else:
        components = [value for value in (readability, professionalism, visualization) if value is not None]
        if components:
            total = sum(components)
        else:
            total = _scan_pattern(
                ("总得分", "总分", "gsb_score", "total_score", "Total Score"), text
            )

    return {
        "readability": readability,
        "professionalism": professionalism,
        "visualization": visualization,
        "total": total,
    }


WEIGHTED_COMPONENTS: tuple[tuple[str, float, float], ...] = (
    ("rubrics_percentage", 0.60, 1.0),
    ("gsb_readability_score", 0.10, 100.0),
    ("gsb_professionalism_score", 0.10, 100.0),
    ("gsb_visualization_score", 0.20, 100.0),
)


# Below this point you can paste remainder of logic from previous version as needed.

def update_gsb_scores(df: pd.DataFrame) -> bool:
    has_text = any(
        col in df.columns for col in ("gsb_text_results", "gsb_results")
    )
    has_vis = "gsb_vis_results" in df.columns
    if not has_text and not has_vis:
        return False
    updated = False
    for idx, row in df.iterrows():
        raw_text = (
            row.get("gsb_text_results")
            if "gsb_text_results" in df.columns
            else row.get("gsb_results")
        )
        raw_vis = row.get("gsb_vis_results") if has_vis else None

        def decode_payload(raw_value: Optional[str]) -> Dict[str, str]:
            if not isinstance(raw_value, str) or not raw_value.strip():
                return {}
            try:
                payload = json.loads(raw_value)
            except json.JSONDecodeError:
                logger.warning(
                    "Failed to decode GSB payload for {}", row.get("instance_id")
                )
                return {}
            if not isinstance(payload, dict):
                return {}
            result: Dict[str, str] = {}
            for key, content in payload.items():
                if isinstance(content, str) and content.strip():
                    result[key] = content
            return result

        payload_text = decode_payload(raw_text)
        payload_vis = decode_payload(raw_vis)
        if not payload_text and not payload_vis:
            continue

        read_scores: list[Optional[float]] = []
        depth_scores: list[Optional[float]] = []
        viz_scores: list[Optional[float]] = []

        for ref_model, content in payload_text.items():
            scores = extract_gsb_scores(content)
            if not scores:
                continue
            prefix = f"gsb_score_{sanitize(str(ref_model))}"
            for key in ("readability", "professionalism"):
                value = scores.get(key)
                if value is None:
                    continue
                col_name = f"{prefix}_{key}"
                df.loc[idx, col_name] = value
                updated = True
            read_scores.append(scores.get("readability"))
            depth_scores.append(scores.get("professionalism"))

        vis_payload_source = payload_vis if payload_vis else payload_text
        for ref_model, content in vis_payload_source.items():
            scores = extract_gsb_scores(content)
            if not scores:
                continue
            value = scores.get("visualization")
            if value is None:
                continue
            prefix = f"gsb_score_{sanitize(str(ref_model))}"
            col_name = f"{prefix}_visualization"
            df.loc[idx, col_name] = value
            updated = True
            viz_scores.append(value)

        agg_read = trans_gsb_score(read_scores)
        agg_depth = trans_gsb_score(depth_scores)
        agg_viz = trans_gsb_score(viz_scores)

        if agg_read is not None:
            df.loc[idx, "gsb_readability_score"] = agg_read
            updated = True
        if agg_depth is not None:
            df.loc[idx, "gsb_professionalism_score"] = agg_depth
            updated = True
        if agg_viz is not None:
            df.loc[idx, "gsb_visualization_score"] = agg_viz
            updated = True

        scores_agg = [val for val in (agg_read, agg_depth, agg_viz) if val is not None]
        if scores_agg:
            combined = max(0.0, sum(scores_agg) / len(scores_agg))
            df.loc[idx, "gsb_total_score"] = combined
            updated = True

    if updated:
        gsb_cols = [col for col in df.columns if col.startswith("gsb_score_")]
        for col in gsb_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "gsb_readability_score" in df.columns:
            df["gsb_readability_score"] = pd.to_numeric(
                df["gsb_readability_score"], errors="coerce"
            )
        if "gsb_professionalism_score" in df.columns:
            df["gsb_professionalism_score"] = pd.to_numeric(
                df["gsb_professionalism_score"], errors="coerce"
            )
        if "gsb_visualization_score" in df.columns:
            df["gsb_visualization_score"] = pd.to_numeric(
                df["gsb_visualization_score"], errors="coerce"
            )
        if "gsb_total_score" in df.columns:
            df["gsb_total_score"] = pd.to_numeric(df["gsb_total_score"], errors="coerce")
    return updated


def compute_weighted_total(df: pd.DataFrame) -> bool:
    required_cols = {name for name, _, _ in WEIGHTED_COMPONENTS}
    if not required_cols.intersection(df.columns):
        return False

    original_scores = (
        df["weighted_total_score"].copy() if "weighted_total_score" in df.columns else None
    )

    def row_weighted_score(row: pd.Series) -> Optional[float]:
        total = 0.0
        weight_sum = 0.0
        for col, weight, scale in WEIGHTED_COMPONENTS:
            if col not in row.index:
                continue
            value = pd.to_numeric(row[col], errors="coerce")
            if pd.isna(value):
                continue
            total += float(value) * scale * weight
            weight_sum += weight
        if weight_sum == 0.0:
            return None
        return total / weight_sum

    df["weighted_total_score"] = df.apply(row_weighted_score, axis=1)

    rubrics_col = "rubrics_percentage"
    gsb_cols = (
        "gsb_readability_score",
        "gsb_professionalism_score",
        "gsb_visualization_score",
    )

    if rubrics_col not in df.columns or any(col not in df.columns for col in gsb_cols):
        df["weighted_total_score"] = pd.NA
    else:
        rubrics_valid = pd.to_numeric(df[rubrics_col], errors="coerce").notna()
        gsb_valid = pd.Series(True, index=df.index)
        for col in gsb_cols:
            gsb_valid &= pd.to_numeric(df[col], errors="coerce").notna()
        combined_valid = rubrics_valid & gsb_valid
        df.loc[~combined_valid, "weighted_total_score"] = pd.NA

    updated = False
    if original_scores is None:
        updated = df["weighted_total_score"].notna().any()
    else:
        updated = not df["weighted_total_score"].equals(original_scores)
    return updated


def compute_gsb_stats(df: pd.DataFrame) -> tuple[float, int] | None:
    if "gsb_total_score" not in df.columns:
        return None
    df["gsb_total_score"] = pd.to_numeric(df["gsb_total_score"], errors="coerce")
    valid = df["gsb_total_score"].dropna()
    if valid.empty:
        return None
    return float(valid.mean()), int(valid.count())


def compute_dimension_stats(
    df: pd.DataFrame, column: str
) -> tuple[float, int] | None:
    if column not in df.columns:
        return None
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.mean()), int(series.count())


def compute_file_score(
    csv_path: Path,
    metadata_map: dict[str, dict[str, int]],
    instance_filter: set[str],
) -> Dict[str, Optional[tuple[float, int]]]:
    df = pd.read_csv(csv_path)
    if instance_filter:
        df = df[df["instance_id"].isin(instance_filter)].reset_index(drop=True)
    results: Dict[str, Optional[tuple[float, int]]] = {
        "rubrics": None,
        "gsb_readability": None,
        "gsb_professionalism": None,
        "gsb_visualization": None,
        "gsb_total": None,
        "weighted_total": None,
        "rubric_completeness": None,
        "rubric_accuracy": None,
        "rubric_conclusiveness": None,
    }

    for column_key in ("Total", "Completeness", "Accuracy", "Conclusiveness"):
        df[column_key] = df["instance_id"].map(
            lambda inst: metadata_map.get(inst, {}).get(column_key)
        )

    for idx, row in df.iterrows():
        raw_text = row.get("rubrics_result")
        has_rubric_text = isinstance(raw_text, str) and raw_text.strip()
        dims = (
            parse_rubric_dimension_scores(raw_text)
            if has_rubric_text
            else {label: None for label in DIMENSION_LABELS}
        )
        for label in DIMENSION_LABELS:
            value = dims.get(label)
            df.at[idx, f"rubric_{label.lower()}_score"] = value if value is not None else pd.NA

    for label in DIMENSION_LABELS:
        raw_col = f"rubric_{label.lower()}_score"
        max_col = label
        pct_col = f"{raw_col}_pct"
        df[pct_col] = pd.to_numeric(df[raw_col], errors="coerce")
        max_series = pd.to_numeric(df[max_col], errors="coerce")
        df[pct_col] = (df[pct_col] / max_series) * 100.0
        df.loc[(max_series.isna()) | (max_series <= 0), pct_col] = pd.NA
        df[pct_col] = pd.to_numeric(df[pct_col], errors="coerce").clip(lower=0, upper=100)

    rubrics_updated = False
    if "rubrics_total_score" in df.columns:
        df["rubrics_total_score"] = pd.to_numeric(
            df["rubrics_total_score"], errors="coerce"
        )
        missing_before = df["rubrics_total_score"].isna().sum()
        for idx, row in df[df["rubrics_total_score"].isna()].iterrows():
            text = row.get("rubrics_result")
            if isinstance(text, str) and text.strip():
                score = extract_total_score(text)
                if score is not None:
                    df.at[idx, "rubrics_total_score"] = score
                    rubrics_updated = True

        missing_after = df["rubrics_total_score"].isna().sum()
        if rubrics_updated:
            logger.info(
                f"{csv_path.name}: filled "
                f"{missing_before - missing_after} rubrics_total_score values."
            )

        df["rubrics_total_score"] = pd.to_numeric(
            df["rubrics_total_score"], errors="coerce"
        )
        df["full_score"] = df["Total"]
        df["rubrics_percentage"] = (
            df["rubrics_total_score"] / df["full_score"] * 100.0
        )
        df["rubrics_percentage"] = pd.to_numeric(
            df["rubrics_percentage"], errors="coerce"
        ).clip(lower=0, upper=100)
        full_missing = df["full_score"].isna().sum()
        if full_missing:
            logger.info(
                f"{csv_path.name}: {full_missing} entries missing full_score metadata."
            )
        invalid_mask = df["full_score"].isna() | (df["full_score"] <= 0)
        df.loc[invalid_mask, "rubrics_percentage"] = pd.NA
        valid = df["rubrics_percentage"].dropna()
        if not valid.empty:
            results["rubrics"] = (float(valid.mean()), int(valid.count()))

        valid_rubric_mask = df["rubrics_percentage"].notna()
        for label in DIMENSION_LABELS:
            pct_col = f"rubric_{label.lower()}_score_pct"
            if pct_col in df.columns:
                df.loc[~valid_rubric_mask, pct_col] = pd.NA

    gsb_updated = update_gsb_scores(df)
    results["gsb_readability"] = compute_dimension_stats(df, "gsb_readability_score")
    results["gsb_professionalism"] = compute_dimension_stats(
        df, "gsb_professionalism_score"
    )
    results["gsb_visualization"] = compute_dimension_stats(
        df, "gsb_visualization_score"
    )
    results["gsb_total"] = compute_gsb_stats(df)
    results["rubric_completeness"] = compute_dimension_stats(
        df, "rubric_completeness_score_pct"
    )
    results["rubric_accuracy"] = compute_dimension_stats(
        df, "rubric_accuracy_score_pct"
    )
    results["rubric_conclusiveness"] = compute_dimension_stats(
        df, "rubric_conclusiveness_score_pct"
    )

    weighted_updated = compute_weighted_total(df)
    results["weighted_total"] = compute_dimension_stats(df, "weighted_total_score")

    if rubrics_updated or gsb_updated or weighted_updated:
        df.to_csv(csv_path, index=False)

    return results


def run_for_language(language: str) -> None:
    language = language.lower()
    if language not in LANGUAGE_CONFIG:
        raise ValueError(f"Unsupported language: {language}")
    lang_cfg = LANGUAGE_CONFIG[language]
    base_dir = Path(__file__).resolve().parent.parent
    scores_dir = base_dir / lang_cfg["scores"]
    src_dir = base_dir / lang_cfg["src"]
    if not src_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")
    if not scores_dir.exists():
        raise FileNotFoundError(f"Scores directory not found: {scores_dir}")

    metadata_map = load_metadata_scores([src_dir])
    if not metadata_map:
        raise RuntimeError("Failed to load any metadata from source directories.")

    prefix = lang_cfg["instance_prefix"]
    instance_filter = {f"{prefix}-{idx:03d}" for idx in DEFAULT_INSTANCE_RANGE}
    for csv_path in sorted(scores_dir.glob("*.csv")):
        try:
            result = compute_file_score(csv_path, metadata_map, instance_filter)
        except KeyError as exc:
            logger.warning(
                "Skipping {} because required column is missing: {}",
                csv_path.name,
                exc,
            )
            continue
        messages: list[str] = []

        def append_stat(
            label: str,
            stats: Optional[tuple[Optional[float], int]],
            multiplier: float = 1.0,
        ) -> None:
            if not stats:
                return
            avg, count = stats
            if avg is None:
                return
            messages.append(f"{label}={(avg * multiplier):.2f} (n={count})")

        append_stat("rubrics", result.get("rubrics"))
        append_stat("Completeness", result.get("rubric_completeness"))
        append_stat("Accuracy", result.get("rubric_accuracy"))
        append_stat("Conclusiveness", result.get("rubric_conclusiveness"))
        append_stat(
            "gsb_readability", result.get("gsb_readability"), multiplier=100.0
        )
        append_stat(
            "gsb_professionalism", result.get("gsb_professionalism"), multiplier=100.0
        )
        append_stat(
            "gsb_visualization", result.get("gsb_visualization"), multiplier=100.0
        )
        append_stat("weighted_total", result.get("weighted_total"))
        if messages:
            print(f"{csv_path.name}: " + "; ".join(messages))
        else:
            print(f"{csv_path.name}: no scores computed.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--language",
        choices=list(LANGUAGE_CONFIG.keys()),
        default="zh",
        help="Which metadata/output language to score (default: zh).",
    )
    args = parser.parse_args()
    run_for_language(args.language)


if __name__ == "__main__":
    main()
