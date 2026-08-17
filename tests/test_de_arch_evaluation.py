import importlib.util
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUITE_DIR = ROOT / "dacomp-de" / "evaluation_suite_arch"
sys.path.insert(0, str(SUITE_DIR))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


scoring = load_module("de_arch_scoring", SUITE_DIR / "utils" / "scoring.py")
config = load_module("de_arch_config", SUITE_DIR / "utils" / "config.py")
evaluation = load_module("de_arch_evaluation", SUITE_DIR / "evaluate.py")


def make_evaluator(en_map=None, zh_map=None):
    evaluator = evaluation.DEDEvaluator.__new__(evaluation.DEDEvaluator)
    evaluator.gold_en_map = en_map or {}
    evaluator.gold_zh_map = zh_map or {}
    evaluator.lock = threading.Lock()
    evaluator.eval_model = "test-model"
    return evaluator


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


def test_language_selection_supports_suffixed_and_legacy_task_names():
    en = {"question": "English question", "rubric": "## [Total Score | 1 Point]."}
    zh = {"question": "中文问题", "rubric": "## [总分 | 1 分]。"}
    evaluator = make_evaluator(
        {"dacomp-de-arch-001": en},
        {"dacomp-de-arch-001-zh": zh},
    )

    assert evaluator._select_gold("dacomp-de-arch-001", "/results/en") == (en, False)
    assert evaluator._select_gold("dacomp-de-arch-001-zh", "/results/en") == (zh, True)
    assert evaluator._select_gold("dacomp-de-arch-001", "/results/arch-zh") == (zh, True)


def test_language_selection_falls_back_from_truncated_english_rubric():
    truncated_en = {
        "question": "English question",
        "rubric": "## [Total Score | 1 Point]\nCriterion starts but is trunc",
    }
    zh = {"question": "中文问题", "rubric": "## [总分 | 1 分]\n标准完整。"}
    evaluator = make_evaluator(
        {"dacomp-de-arch-001": truncated_en},
        {"dacomp-de-arch-001-zh": zh},
    )

    assert evaluator._select_gold("dacomp-de-arch-001", "/results/en") == (zh, True)


@pytest.mark.parametrize(
    "rubric",
    [
        "",
        "Criterion without a total score.",
        "## [Total Score | 1 Point]\nCriterion is trunc",
    ],
)
def test_missing_or_truncated_rubric_is_rejected(rubric):
    evaluator = make_evaluator()
    assert not evaluator._rubric_is_complete(rubric)


def test_empty_blueprint_scores_zero_without_calling_judge(tmp_path):
    task_name = "dacomp-de-arch-001"
    (tmp_path / f"{task_name}.yaml").write_text(" \n", encoding="utf-8")
    gold = {
        "question": "Question",
        "rubric": "## [Total Score | 7 Points]\nComplete criterion.",
    }
    evaluator = make_evaluator({task_name: gold})
    evaluator.call_llm_api = lambda *_args, **_kwargs: pytest.fail(
        "judge must not be called for an empty blueprint"
    )

    result = evaluator.evaluate_single_task(str(tmp_path), task_name)

    assert result["actual_score"] == 0
    assert result["max_score"] == 7
    assert result["error"] == f"Blueprint is empty for task {task_name}"


def test_failed_tasks_remain_in_summary_denominator():
    evaluator = make_evaluator()
    results = [
        {"task_name": "ok", "actual_score": 4, "max_score": 5},
        {"task_name": "empty", "actual_score": 0, "max_score": 7, "error": "empty"},
    ]

    summary = evaluator.create_summary(results)

    assert summary["total_actual_score"] == 4
    assert summary["total_max_score"] == 12
    assert summary["overall_score_rate"] == pytest.approx(4 / 12)


def test_all_shipped_tasks_resolve_to_complete_rubrics():
    evaluator = make_evaluator(
        evaluation.DEDEvaluator._load_gold_jsonl(
            make_evaluator(), config.DEFAULT_GOLD_EN_JSONL
        ),
        evaluation.DEDEvaluator._load_gold_jsonl(
            make_evaluator(), config.DEFAULT_GOLD_ZH_JSONL
        ),
    )

    for task_name in evaluator.gold_en_map:
        gold, _is_zh = evaluator._select_gold(task_name, "/results/en")
        assert evaluator._rubric_is_complete(gold["rubric"]), task_name
