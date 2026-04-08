from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from extractor import identify_failed_subquestions, run_extractor, save_evidence_notes
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
    failed_subquestions: list[str]


def _planner_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    plan = generate_research_plan(state["user_query"])
    return {"plan": plan}


def _searcher_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    all_subquestions = list(state["plan"].subquestions)
    previous_results = dict(state.get("search_results", {}))
    failed_subquestions = state.get("failed_subquestions", [])
    failed_lookup = set(failed_subquestions)

    # On retry, only refresh weak subquestions when we have a clear failure list.
    is_targeted_retry = state.get("retry_count", 0) > 0 and bool(failed_subquestions)
    subquestions_to_search = (
        [subquestion for subquestion in all_subquestions if subquestion in failed_lookup]
        if is_targeted_retry
        else all_subquestions
    )

    if is_targeted_retry:
        print(f"Targeted search retry for {len(subquestions_to_search)} subquestions")

    updated_results = run_searcher(
        plan=state["plan"],
        max_results=state["max_results"],
        subquestions=subquestions_to_search,
    )

    merged_results = previous_results if is_targeted_retry else {}
    for subquestion in subquestions_to_search:
        merged_results[subquestion] = updated_results.get(subquestion, [])

    # Keep full grouped structure so artifacts always represent complete state.
    ordered_results = {
        subquestion: merged_results.get(subquestion, []) for subquestion in all_subquestions
    }

    search_path = save_search_results(ordered_results)
    return {
        "search_results": ordered_results,
        "search_results_path": str(search_path),
    }


def _extractor_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    all_subquestions = list(state["plan"].subquestions)
    previous_notes = dict(state.get("extracted_notes", {}))
    failed_subquestions = state.get("failed_subquestions", [])
    failed_lookup = set(failed_subquestions)

    # Retry only weak subquestions to avoid recomputing strong areas.
    is_targeted_retry = state.get("retry_count", 0) > 0 and bool(failed_subquestions)
    subquestions_to_extract = (
        [subquestion for subquestion in all_subquestions if subquestion in failed_lookup]
        if is_targeted_retry
        else all_subquestions
    )

    if is_targeted_retry:
        print(f"Targeted extraction retry for {len(subquestions_to_extract)} subquestions")

    extraction_input = {
        subquestion: state["search_results"].get(subquestion, [])
        for subquestion in subquestions_to_extract
    }
    updated_notes = run_extractor(
        grouped_results=extraction_input,
        max_notes_per_subquestion=state["max_notes"],
    )

    merged_notes = previous_notes if is_targeted_retry else {}
    for subquestion in subquestions_to_extract:
        merged_notes[subquestion] = updated_notes.get(subquestion, [])

    ordered_notes = {
        subquestion: merged_notes.get(subquestion, []) for subquestion in all_subquestions
    }
    failed_after_extraction = identify_failed_subquestions(
        grouped_results=state["search_results"],
        grouped_notes=ordered_notes,
        ordered_subquestions=all_subquestions,
    )

    notes_path = save_evidence_notes(ordered_notes)
    return {
        "extracted_notes": ordered_notes,
        "notes_output_path": str(notes_path),
        "failed_subquestions": failed_after_extraction,
    }


def _writer_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    revision_instructions: list[str] | None = None
    weak_sections: list[str] | None = None
    if state.get("retry_count", 0) > 0:
        review = state.get("review_decision")
        if review is not None:
            revision_instructions = review.revision_instructions
            weak_sections = review.weak_sections

    report = generate_report(
        plan=state["plan"],
        extracted_notes=state["extracted_notes"],
        report_title=state.get("report_title"),
        revision_instructions=revision_instructions,
        weak_sections=weak_sections,
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


def _prepare_retry_node(state: ResearchWorkflowState) -> ResearchWorkflowState:
    review = state["review_decision"]
    retry_reason = "search" if review.needs_more_research else "write"
    print(f"Retry triggered: {retry_reason}")
    if review.needs_more_research:
        failed_subquestions = state.get("failed_subquestions", [])
        if failed_subquestions:
            joined = ", ".join(failed_subquestions)
            print(f"Retrying {len(failed_subquestions)} failed subquestions: {joined}")
        else:
            print("Retrying research for all subquestions")
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "retry_triggered": True,
    }


def _route_after_review(state: ResearchWorkflowState) -> str:
    review = state["review_decision"]
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if review.approved:
        return "approved"

    if retry_count >= max_retries:
        return "failed"

    if review.needs_more_research:
        return "retry_search"

    return "retry_write"


def _route_after_prepare_retry(state: ResearchWorkflowState) -> str:
    review = state["review_decision"]
    if review.needs_more_research:
        return "retry_search"
    return "retry_write"


def _build_workflow():
    graph = StateGraph(ResearchWorkflowState)

    graph.add_node("planner", _planner_node)
    graph.add_node("searcher", _searcher_node)
    graph.add_node("extractor", _extractor_node)
    graph.add_node("writer", _writer_node)
    graph.add_node("reviewer", _reviewer_node)
    graph.add_node("prepare_retry", _prepare_retry_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "searcher")
    graph.add_edge("searcher", "extractor")
    graph.add_edge("extractor", "writer")
    graph.add_edge("writer", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        _route_after_review,
        {
            "approved": END,
            "retry_search": "prepare_retry",
            "retry_write": "prepare_retry",
            "failed": END,
        },
    )
    graph.add_conditional_edges(
        "prepare_retry",
        _route_after_prepare_retry,
        {
            "retry_search": "searcher",
            "retry_write": "writer",
        },
    )

    return graph.compile()


_WORKFLOW = _build_workflow()


def run_research_workflow(
    user_query: str,
    max_results: int = 5,
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
        "failed_subquestions": [],
    }
    final_state = _WORKFLOW.invoke(
        initial_state,
        config={
            "run_name": "researchpp_run",
            "metadata": {
                "query": user_query,
                "max_results": max_results,
                "max_notes": max_notes,
                "max_retries": max_retries,
            },
        },
    )

    # Keep a stable final artifact path for demos, regardless of retry behavior.
    final_report_path = Path(__file__).resolve().parent / "outputs" / "final_report.md"
    final_report_path.parent.mkdir(parents=True, exist_ok=True)
    final_report_path.write_text(final_state["report_markdown"], encoding="utf-8")
    final_state["final_report_path"] = str(final_report_path)

    return final_state
