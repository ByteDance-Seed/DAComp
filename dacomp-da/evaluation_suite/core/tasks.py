from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import pandas as pd
from loguru import logger

from .llm_client import llm_completion

JSON_BLOCK_PATTERN = re.compile(
    r"```json\s*(\{.*?\})\s*```", flags=re.DOTALL | re.IGNORECASE
)
MAX_RUBRICS_ATTEMPTS = 10
MAX_GSB_ATTEMPTS = 10
TARGET_KEYS = {"总得分", "总分", "score", "total_score"}


@dataclass
class EvaluationTask:
    instance_id: str
    model_name: str
    query: str
    rubrics: str
    trajectory: str
    answer: str
    answer_path: Optional[Path] = None
    answer_images: List[Path] = field(default_factory=list)
    reference_reports: Dict[str, str] = field(default_factory=dict)
    rubrics_result: Optional[str] = None
    rubrics_total_score: Optional[float] = None
    gsb_text_results: Dict[str, Optional[str]] = field(default_factory=dict)
    gsb_vis_results: Dict[str, Optional[str]] = field(default_factory=dict)
    need_rubrics: bool = False
    need_gsb_text: bool = False
    need_gsb_vis: bool = False
    gsb_refs: Dict[str, str] = field(default_factory=dict)
    gsb_text_pending_refs: Set[str] = field(default_factory=set)
    gsb_vis_pending_refs: Set[str] = field(default_factory=set)
    reference_images: Dict[str, List[Path]] = field(default_factory=dict)
    rubric_prompt_template: str = ""
    gsb_text_prompt_template: str = ""
    gsb_vis_prompt_template: str = ""
    rubrics_attempts: int = 0
    gsb_text_attempts: Dict[str, int] = field(default_factory=dict)
    gsb_vis_attempts: Dict[str, int] = field(default_factory=dict)

    def _encode_images(self, image_paths: Iterable[Path]) -> List[dict]:
        segments: List[dict] = []
        for image_path in image_paths:
            try:
                data = Path(image_path).read_bytes()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to read image for evaluation",
                    instance_id=self.instance_id,
                    image=str(image_path),
                    error=str(exc),
                )
                continue
            mime_type, _ = mimetypes.guess_type(str(image_path))
            if not mime_type:
                mime_type = "image/png"
            encoded = base64.b64encode(data).decode("ascii")
            segments.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{encoded}",
                    },
                }
            )
        return segments

    def rubrics_prompt(self) -> List[dict]:
        history_payload = self.trajectory or self.answer or ""
        if history_payload and isinstance(history_payload, str):
            history_payload = json.dumps(
                [{"role": "assistant", "content": history_payload}],
                ensure_ascii=False,
            )

        base_text = self.rubric_prompt_template.format(
            user_query=self.query,
            assistant_response=history_payload,
            rubric=self.rubrics,
        )

        return [{"role": "user", "content": [{"type": "text", "text": base_text}]}]

    def gsb_prompts(
        self,
        prompt_template: str,
        include_images: bool,
    ) -> Iterable[tuple[str, List[dict]]]:
        eval_report = self.answer or ""
        answer_image_segments = (
            self._encode_images(self.answer_images) if include_images else []
        )
        for ref_model, ref_report in self.reference_reports.items():
            prompt_text = prompt_template.format(
                content1=eval_report,
                content2=ref_report or "",
            )
            content_segments: List[dict] = [{"type": "text", "text": prompt_text}]
            if include_images and answer_image_segments:
                content_segments.append({"type": "text", "text": "\n[被评测报告图片附件]"})
                content_segments.extend(answer_image_segments)

            if include_images:
                ref_image_segments = self._encode_images(
                    self.reference_images.get(ref_model, [])
                )
                if ref_image_segments:
                    content_segments.append({"type": "text", "text": "\n[参考报告图片附件]"})
                    content_segments.extend(ref_image_segments)

            yield ref_model, [{"role": "user", "content": content_segments}]

    def eval_rubrics(self, config_name: str) -> None:
        if not self.rubrics:
            logger.warning(f"No rubrics for {self.instance_id}, skip rubrics eval.")
            return
        if not (self.trajectory or self.answer):
            logger.warning(
                f"No trajectory/answer for {self.instance_id}, skip rubrics eval."
            )
            return
        prompt = self.rubrics_prompt()
        self.rubrics_attempts += 1
        resp = llm_completion(prompt, model_config_name=config_name)
        content = resp.content if resp else None
        if not content:
            logger.warning(
                "Empty rubrics response received",
                instance_id=self.instance_id,
            )
            self.need_rubrics = True
            self.rubrics_result = None
            self.rubrics_total_score = None
            return
        if not is_valid_rubrics_response(content):
            logger.warning(
                "Rubrics response is not valid JSON.",
                instance_id=self.instance_id,
            )
            self.need_rubrics = True
            self.rubrics_result = None
            self.rubrics_total_score = None
            return
        score = extract_total_score(content)
        if score is None:
            logger.warning(
                "Rubrics response missing total score.",
                instance_id=self.instance_id,
            )
            self.need_rubrics = True
            self.rubrics_result = None
            self.rubrics_total_score = None
            return
        self.rubrics_result = content
        self.rubrics_total_score = score
        self.need_rubrics = False

    def eval_gsb(
        self,
        *,
        config_name: str,
        include_images: bool,
        channel: str,
        prompt_template: str,
    ) -> None:
        if not self.reference_reports:
            logger.warning(
                f"No GSB references for {self.instance_id}, skip GSB eval."
            )
            if channel == "text":
                self.need_gsb_text = False
                self.gsb_text_pending_refs.clear()
            else:
                self.need_gsb_vis = False
                self.gsb_vis_pending_refs.clear()
            return
        if not self.answer:
            logger.warning(f"No answer for {self.instance_id}, skip GSB eval.")
            if channel == "text":
                self.need_gsb_text = False
                self.gsb_text_pending_refs.clear()
            else:
                self.need_gsb_vis = False
                self.gsb_vis_pending_refs.clear()
            return

        pending_refs = (
            self.gsb_text_pending_refs if channel == "text" else self.gsb_vis_pending_refs
        )
        results = self.gsb_text_results if channel == "text" else self.gsb_vis_results
        attempts = self.gsb_text_attempts if channel == "text" else self.gsb_vis_attempts

        for ref_model, prompt in self.gsb_prompts(prompt_template, include_images):
            if pending_refs and ref_model not in pending_refs:
                continue
            attempts[ref_model] = attempts.get(ref_model, 0) + 1
            resp = llm_completion(prompt, model_config_name=config_name)
            content = resp.content if resp else None
            if not content:
                logger.warning(
                    "Empty GSB response received",
                    instance_id=self.instance_id,
                    reference=ref_model,
                    channel=channel,
                )
                continue
            if not is_valid_gsb_response(content):
                logger.warning(
                    "GSB response is not valid JSON.",
                    instance_id=self.instance_id,
                    reference=ref_model,
                    channel=channel,
                )
                preview = content.strip().replace("\n", " ")
                logger.debug(
                    "GSB raw response preview",
                    instance_id=self.instance_id,
                    reference=ref_model,
                    response_preview=preview[:500],
                )
                continue
            results[ref_model] = content
            if ref_model in pending_refs:
                pending_refs.discard(ref_model)

        if channel == "text":
            self.need_gsb_text = bool(pending_refs)
        else:
            self.need_gsb_vis = bool(pending_refs)


def _strip_json_block(text: str) -> str:
    trimmed = text.strip()
    if not trimmed:
        return ""
    if trimmed.startswith("```"):
        parts = trimmed.split("\n", 1)
        body = parts[1] if len(parts) > 1 else ""
        end_split = body.rsplit("```", 1)
        body = end_split[0] if len(end_split) > 1 else body
        return body.strip()
    match = JSON_BLOCK_PATTERN.search(trimmed)
    if match:
        return match.group(1).strip()
    return trimmed


def parse_json_response(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    text = _strip_json_block(raw)
    if not text:
        return None
    try:
        candidate = json.loads(text)
        return candidate
    except Exception:
        cleaned = re.sub(r":\s*\+(\d+(?:\.\d+)?)", r": \1", text)
        cleaned = re.sub(r"\\(?![\"\\/bfnrtu0-9])", r"\\\\", cleaned)
        try:
            candidate = json.loads(cleaned)
            return candidate
        except Exception:
            return None


def is_valid_json_dict(raw: Optional[str]) -> bool:
    data = parse_json_response(raw)
    return isinstance(data, dict)


def is_valid_rubrics_response(raw: Optional[str]) -> bool:
    return is_valid_json_dict(raw)


def is_valid_gsb_response(raw: Optional[str]) -> bool:
    return is_valid_json_dict(raw)


def _collect_scores(obj: Any, acc: list[Optional[float]]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in TARGET_KEYS:
                acc.append(to_optional_float(value))
            _collect_scores(value, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_scores(item, acc)


def extract_total_score(result: Optional[str]) -> Optional[float]:
    if not result:
        return None
    data = parse_json_response(result)
    if data is None:
        logger.debug("Failed to parse rubrics result JSON.")
        pattern = re.compile(
            r"[\"']?(?:总得分|总分|score|total_score)[\"']?\s*[:=：]\s*(-?\d+(?:\.\d+)?)"
        )
        matches = pattern.findall(result)
        if matches:
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

    scores: list[Optional[float]] = []
    _collect_scores(data, scores)
    for score in reversed(scores):
        if score is not None:
            return score
    return None


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


__all__ = [
    "EvaluationTask",
    "MAX_GSB_ATTEMPTS",
    "MAX_RUBRICS_ATTEMPTS",
    "extract_total_score",
    "is_valid_gsb_response",
    "is_valid_rubrics_response",
    "parse_json_response",
    "to_optional_float",
]
