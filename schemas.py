from typing import List

from pydantic import BaseModel


class ResearchPlan(BaseModel):
    """Structured planner output returned by the model."""

    research_goal: str
    subquestions: List[str]
    report_outline: List[str]
