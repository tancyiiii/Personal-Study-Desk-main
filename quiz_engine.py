"""Deterministic grading for locally rendered structured quizzes."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _normalize_option(answer: str) -> str:
    match = re.search(r"\b([A-Da-d])\b", answer)
    return match.group(1).upper() if match else ""


def _normalize_boolean(answer: str) -> str:
    text = answer.strip().lower()
    if text in {"true", "t", "yes", "对", "是", "正确", "√"}:
        return "true"
    if text in {"false", "f", "no", "错", "否", "错误", "×", "x"}:
        return "false"
    return text


def _is_correct(question: Dict[str, Any], submitted: str) -> bool:
    question_type = question.get("question_type", "short_answer")
    expected = str(question.get("answer", "")).strip()
    submitted = str(submitted or "").strip()

    if question_type == "single_choice":
        return bool(expected) and _normalize_option(submitted) == _normalize_option(expected)
    if question_type == "true_false":
        return bool(expected) and _normalize_boolean(submitted) == _normalize_boolean(expected)
    return False


def grade_quiz(
    questions: List[Dict[str, Any]],
    answers: Dict[int, str],
) -> Tuple[int, int, List[Dict[str, Any]]]:
    """Return correct_count, auto_graded_count, and per-question results."""
    results: List[Dict[str, Any]] = []
    correct = 0
    auto_graded = 0
    for index, question in enumerate(questions):
        submitted = answers.get(index, "")
        question_type = question.get("question_type", "short_answer")
        if question_type in {"single_choice", "true_false"}:
            auto_graded += 1
            is_correct = _is_correct(question, submitted)
            if is_correct:
                correct += 1
        else:
            is_correct = False
        results.append(
            {
                "index": index,
                "question_type": question_type,
                "submitted": submitted,
                "is_correct": is_correct,
            }
        )
    return correct, auto_graded, results

