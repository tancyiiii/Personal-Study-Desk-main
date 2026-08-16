"""Structured response models shared by the business and agent layers."""

from typing import List, Optional

from pydantic import BaseModel, Field


class QuizQuestion(BaseModel):
    question: str
    question_type: str = Field(
        default="single_choice",
        description="One of: single_choice, true_false, short_answer",
    )
    options: List[str] = Field(default_factory=list)
    answer: str
    explanation: str = ""
    core_concept: str = ""


class QuizSet(BaseModel):
    questions: List[QuizQuestion] = Field(default_factory=list)

