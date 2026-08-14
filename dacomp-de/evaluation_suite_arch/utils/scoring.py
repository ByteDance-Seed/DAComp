from typing import Any

TOTAL_SCORE_KEYS = ("总得分", "Total Score", "total_score")


def extract_actual_score(evaluation_result: dict[str, Any]) -> int:
    """Extract a bilingual total score from a DE-Arch judge response."""
    for key in TOTAL_SCORE_KEYS:
        if key in evaluation_result:
            return evaluation_result[key]

    if "parse_error" in evaluation_result:
        return 0

    total_score = 0
    for value in evaluation_result.values():
        if not isinstance(value, dict):
            continue
        for key in TOTAL_SCORE_KEYS:
            if key in value:
                total_score += value[key]
                break
    return total_score
