from typing import List

from pydantic import BaseModel, Field


class ResearchPlan(BaseModel):
    """Structured planner output returned by the model."""

    research_goal: str
    subquestions: List[str]
    report_outline: List[str]


class SearchResult(BaseModel):
    """Single normalized web search result."""

    title: str
    url: str
    snippet: str


class EvidenceNote(BaseModel):
    """One extracted evidence note tied to a specific source."""

    subquestion: str
    source_title: str
    source_url: str
    key_point: str
    evidence: str
    relevance_reason: str
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidenceNoteList(BaseModel):
    """Container for structured-output extraction responses."""

    notes: List[EvidenceNote]


class ReviewDecision(BaseModel):
    """Structured decision produced by the reviewer stage."""

    approved: bool
    overall_assessment: str
    support_gaps: List[str]
    revision_instructions: List[str]
    needs_more_research: bool
    weak_sections: List[str] = []
    confidence: str | None = None
