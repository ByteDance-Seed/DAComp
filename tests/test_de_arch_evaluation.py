import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUITE_DIR = ROOT / "dacomp-de" / "evaluation_suite_arch"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


scoring = load_module("de_arch_scoring", SUITE_DIR / "utils" / "scoring.py")
config = load_module("de_arch_config", SUITE_DIR / "utils" / "config.py")


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"总得分": 12}, 12),
        ({"Total Score": 11}, 11),
        ({"total_score": 10}, 10),
        (
            {
                "Requirement 1": {"Total Score": 4},
                "Requirement 2": {"总得分": 5},
                "Requirement 3": {"total_score": 3},
            },
            12,
        ),
        ({"parse_error": "invalid JSON", "raw_content": "{"}, 0),
    ],
)
def test_extract_actual_score_supports_bilingual_responses(result, expected):
    assert scoring.extract_actual_score(result) == expected


def test_default_gold_paths_point_to_shipped_files():
    assert config.DEFAULT_GOLD_EN_JSONL.is_file()
    assert config.DEFAULT_GOLD_ZH_JSONL.is_file()
    assert config.DEFAULT_GOLD_EN_JSONL.parent == SUITE_DIR / "gold"
    assert config.DEFAULT_GOLD_ZH_JSONL.parent == SUITE_DIR / "gold"


def test_default_results_path_is_relative_to_evaluation_suite():
    assert config.DEFAULT_RESULTS_DIR == SUITE_DIR / "results"
