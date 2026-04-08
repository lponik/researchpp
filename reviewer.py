import json
from pathlib import Path

from langchain_openai import ChatOpenAI

from schemas import EvidenceNote, ResearchPlan, ReviewDecision


def review_report(
    plan: ResearchPlan,
    extracted_notes: dict[str, list[EvidenceNote]],
    report_markdown: str,
) -> ReviewDecision:
    """
    Review a generated report against the extracted evidence notes.

    The reviewer evaluates support quality; it does not retrieve new information.
    """
    llm = ChatOpenAI(model="gpt-4o-mini")
    reviewer_llm = llm.with_structured_output(ReviewDecision)

    notes_payload = {
        subquestion: [note.model_dump(exclude_none=True) for note in notes]
        for subquestion, notes in extracted_notes.items()
    }

    prompt = f"""
You are a quality reviewer for a research workflow.

Your job:
- Evaluate whether the report is well supported by the extracted evidence notes.
- Be conservative about unsupported claims.
- Prefer flagging support weaknesses over blind approval.

Evaluation criteria:
1. Does the report address the research goal?
2. Are key findings grounded in extracted evidence notes?
3. Are there weak, vague, repetitive, or unsupported sections?
4. Is another research pass needed to strengthen support?

Rules:
- Treat extracted evidence notes as source of truth.
- Judge the report only against provided plan + evidence notes.
- Do not perform retrieval or add outside facts.
- Focus on substantive support issues, not minor style nitpicks.
- Return structured output only.

Research plan (JSON):
{json.dumps(plan.model_dump(), indent=2, ensure_ascii=False)}

Extracted evidence notes (JSON):
{json.dumps(notes_payload, indent=2, ensure_ascii=False)}

Report to review (markdown):
{report_markdown}
""".strip()

    try:
        return reviewer_llm.invoke(prompt)
    except Exception as exc:
        raise RuntimeError("Failed to review generated report.") from exc


def save_review_decision(
    decision: ReviewDecision,
    retry_count: int,
    output_path: str | Path | None = None,
) -> Path:
    """Save the latest review decision to JSON for inspection."""
    if output_path is None:
        output_path = Path(__file__).resolve().parent / "outputs" / "review.json"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "retry_count": retry_count,
        "review_decision": decision.model_dump(exclude_none=True),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def summarize_review_decision(decision: ReviewDecision) -> str:
    """Build a short terminal-friendly summary of the reviewer output."""
    status = "approved" if decision.approved else "needs revision"
    return (
        f"Review status: {status}\n"
        f"Needs more research: {decision.needs_more_research}\n"
        f"Support gaps found: {len(decision.support_gaps)}"
    )
