from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List


GSB_REF_KEYS = [f"gsb_ref_{idx}" for idx in range(5)]
IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _resolve_images(markdown: str, base_dir: Path) -> List[str]:
    images: List[str] = []
    for match in IMAGE_PATTERN.findall(markdown):
        if "://" in match or match.startswith("/"):
            continue
        candidate = (base_dir / match).expanduser()
        resolved = candidate.resolve()
        if resolved.exists():
            images.append(str(resolved))
    return images


def load_task_metadata(source: Path) -> Dict[str, Dict[str, object]]:
    source = source.expanduser()
    if not source.exists():
        raise FileNotFoundError(f"Task metadata source not found: {source}")
    if not source.is_dir():
        raise ValueError(
            f"Metadata source must be a directory rooted at per-instance folders: {source}"
        )

    metadata: Dict[str, Dict[str, object]] = {}
    for instance_dir in sorted(p for p in source.iterdir() if p.is_dir()):
        instance_id = instance_dir.name
        rubric_path = instance_dir / "rubric.txt"
        instruction_path = instance_dir / "instruction.txt"
        rubrics = _read_text(rubric_path) if rubric_path.exists() else ""
        instruction = _read_text(instruction_path) if instruction_path.exists() else ""

        gsb_refs: Dict[str, str] = {}
        gsb_ref_images: Dict[str, List[str]] = {}
        for key in GSB_REF_KEYS:
            ref_dir = instance_dir / key
            text = ""
            images: List[str] = []
            if ref_dir.is_dir():
                md_files = sorted(ref_dir.glob("*.md"))
                if md_files:
                    text = _read_text(md_files[0])
                    images = _resolve_images(text, ref_dir)
            gsb_refs[key] = text
            gsb_ref_images[key] = images

        metadata[instance_id] = {
            "rubrics": rubrics,
            "instruction": instruction,
            "gsb_refs": gsb_refs,
            "gsb_ref_images": gsb_ref_images,
        }
    return metadata
