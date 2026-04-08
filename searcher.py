import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from schemas import ResearchPlan, SearchResult


def search_subquestion(subquestion: str, max_results: int = 3) -> list[SearchResult]:
    """
    Search the web for a single subquestion and normalize the output.

    Requires `TAVILY_API_KEY` in the environment for Tavily.
    """
    try:
        # Preferred Tavily integration for LangChain (replaces deprecated class).
        from langchain_tavily import TavilySearch
    except ImportError as exc:
        raise RuntimeError(
            "Missing search dependencies. Run `uv sync` to install `langchain-tavily`."
        ) from exc

    tool = TavilySearch(max_results=max_results)

    try:
        raw_response = tool.invoke({"query": subquestion})
    except Exception as exc:
        raise RuntimeError(f"Search failed for subquestion: {subquestion}") from exc

    if isinstance(raw_response, dict) and isinstance(raw_response.get("results"), list):
        raw_results = raw_response["results"]
    elif isinstance(raw_response, list):
        raw_results = raw_response
    else:
        raw_results = []

    normalized_results: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()

        normalized_results.append(
            SearchResult(
                title=title or "Untitled result",
                url=url,
                snippet=snippet or "No snippet provided.",
            )
        )

    return normalized_results


def run_searcher(
    plan: ResearchPlan, max_results: int = 3
) -> dict[str, list[SearchResult]]:
    """Run deterministic search over every planner subquestion."""
    subquestions = list(plan.subquestions)
    if not subquestions:
        return {}

    print(f"Running search for {len(subquestions)} subquestions in parallel")

    # Searches are independent and mostly I/O-bound, so thread fan-out is safe.
    max_workers = min(8, len(subquestions))
    grouped_results: dict[str, list[SearchResult]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for subquestion, results in executor.map(
            _search_one_subquestion,
            subquestions,
            [max_results] * len(subquestions),
        ):
            grouped_results[subquestion] = results

    return grouped_results


def _search_one_subquestion(
    subquestion: str, max_results: int
) -> tuple[str, list[SearchResult]]:
    try:
        results = search_subquestion(subquestion=subquestion, max_results=max_results)
    except Exception:
        # Keep pipeline moving even if one search call fails.
        results = []
    return subquestion, results


def save_search_results(
    grouped_results: dict[str, list[SearchResult]],
    output_path: str | Path | None = None,
) -> Path:
    """Persist grouped search results for easy inspection."""
    if output_path is None:
        output_path = Path(__file__).resolve().parent / "outputs" / "search_results.json"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        subquestion: [result.model_dump() for result in results]
        for subquestion, results in grouped_results.items()
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
