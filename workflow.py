from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from extractor import run_extractor, save_evidence_notes
from planner import generate_research_plan
from reviewer import review_report, save_review_decision
from schemas import EvidenceNote, ResearchPlan, ReviewDecision, SearchResult
from searcher import run_searcher, save_search_results
from writer import generate_report, save_report


class ResearchWorkflowState(TypedDict, total=False):
    """Shared state passed between workflow nodes."""

    user_query: str
    plan: ResearchPlan
    search_results: dict[str, list[SearchResult]]
    extracted_notes: dict[str, list[EvidenceNote]]
    report_markdown: str
    review_decision: ReviewDecision
    retry_count: int
    max_retries: int
    max_results: int
    max_notes: int
    report_title: str | None
    report_output: str | None
    search_results_path: str
    notes_output_path: str
    report_output_path: str
    review_output_path: str
    final_report_path: str
    retry_triggered: bool


def _planner_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    plan = generate_research_plan(state["user_query"])
    return {"plan": plan}


def _searcher_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    grouped_results = run_searcher(plan=state["plan"], max_results=state["max_results"])
    search_path = save_search_results(grouped_results)
    return {
        "search_results": grouped_results,
        "search_results_path": str(search_path),
    }


def _extractor_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    grouped_notes = run_extractor(
        grouped_results=state["search_results"],
        max_notes_per_subquestion=state["max_notes"],
    )
    notes_path = save_evidence_notes(grouped_notes)
    return {
        "extracted_notes": grouped_notes,
        "notes_output_path": str(notes_path),
    }


def _writer_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    report = generate_report(
        plan=state["plan"],
        extracted_notes=state["extracted_notes"],
        report_title=state.get("report_title"),
    )

    report_output = state.get("report_output")
    if report_output is None:
        base = Path(__file__).resolve().parent / "outputs"
        filename = "report.md" if state.get("retry_count", 0) == 0 else "revised_report.md"
        report_output = str(base / filename)

    report_path = save_report(markdown_report=report, output_path=report_output)
    return {
        "report_markdown": report,
        "report_output_path": str(report_path),
    }


def _reviewer_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    decision = review_report(
        plan=state["plan"],
        extracted_notes=state["extracted_notes"],
        report_markdown=state["report_markdown"],
    )
    review_path = save_review_decision(decision=decision, retry_count=state.get("retry_count", 0))
    return {
        "review_decision": decision,
        "review_output_path": str(review_path),
    }


def _retry_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    # v1 retry strategy: rerun one additional full research pass for all subquestions.
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "retry_triggered": True,
    }


def _route_after_review(state: ResearchWorkflowState) -> str:
    decision = state["review_decision"]
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if decision.approved or not decision.needs_more_research:
        return "finish"

    if retry_count >= max_retries:
        return "finish"

    return "retry"


def _build_workflow():
    graph = StateGraph(ResearchWorkflowState)

    graph.add_node("planner", _planner_node)
    graph.add_node("searcher", _searcher_node)
    graph.add_node("extractor", _extractor_node)
    graph.add_node("writer", _writer_node)
    graph.add_node("reviewer", _reviewer_node)
    graph.add_node("retry", _retry_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "searcher")
    graph.add_edge("searcher", "extractor")
    graph.add_edge("extractor", "writer")
    graph.add_edge("writer", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        _route_after_review,
        {
            "retry": "retry",
            "finish": END,
        },
    )
    graph.add_edge("retry", "searcher")

    return graph.compile()


_WORKFLOW = _build_workflow()


def run_research_workflow(
    user_query: str,
    max_results: int = 3,
    max_notes: int = 4,
    report_title: str | None = None,
    report_output: str | None = None,
    max_retries: int = 1,
) -> ResearchWorkflowState:
    """Run the full research workflow with one bounded conditional retry."""
    initial_state: ResearchWorkflowState = {
        "user_query": user_query,
        "retry_count": 0,
        "max_retries": max_retries,
        "max_results": max_results,
        "max_notes": max_notes,
        "report_title": report_title,
        "report_output": report_output,
        "retry_triggered": False,
    }
    final_state = _WORKFLOW.invoke(initial_state)

    # Keep a stable final artifact path for demos, regardless of retry behavior.
    final_report_path = Path(__file__).resolve().parent / "outputs" / "final_report.md"
    final_report_path.parent.mkdir(parents=True, exist_ok=True)
    final_report_path.write_text(final_state["report_markdown"], encoding="utf-8")
    final_state["final_report_path"] = str(final_report_path)

    return final_state
