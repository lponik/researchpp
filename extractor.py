import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from langchain_openai import ChatOpenAI

from schemas import EvidenceNote, EvidenceNoteList, SearchResult


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    haystack = f" {text.lower()} "
    return any(marker in haystack for marker in markers)


def _is_high_value_note(note: EvidenceNote) -> bool:
    key_point = note.key_point.strip()
    evidence = note.evidence.strip()
    relevance_reason = note.relevance_reason.strip()

    if len(evidence.split()) < 10:
        return False

    key_point_lower = key_point.lower()
    combined_lower = f"{key_point} {evidence} {relevance_reason}".lower()

    vague_markers = (
        " may ",
        " can ",
        " could ",
        " tends to ",
        " helps ",
        " improves ",
        " useful ",
        " generally ",
        " often ",
    )
    if _contains_any(key_point_lower, vague_markers):
        return False

    generic_markers = (
        "is important",
        "is useful",
        "is beneficial",
        "plays a role",
        "widely used",
        "good for",
        "helpful for",
    )
    if _contains_any(combined_lower, generic_markers):
        return False

    comparison_markers = (
        " vs ",
        " versus ",
        " compared to ",
        " faster than ",
        " slower than ",
        " lower than ",
        " higher than ",
        " more than ",
        " less than ",
        " tradeoff ",
        " trade-off ",
        " whereas ",
        " outperforms ",
        " underperforms ",
    )
    mechanism_markers = (
        " because ",
        " due to ",
        " retrieval ",
        " rerank ",
        " reranking ",
        " chunk ",
        " context window ",
        " token ",
        " embedding ",
        " index ",
        " latency ",
        " throughput ",
        " precision ",
        " recall ",
        " bottleneck ",
        " cache ",
    )

    has_number = any(ch.isdigit() for ch in combined_lower)
    has_comparison = _contains_any(combined_lower, comparison_markers)
    has_mechanism = _contains_any(combined_lower, mechanism_markers)

    return has_number or has_comparison or has_mechanism


def _filter_high_value_notes(notes: list[EvidenceNote], max_notes: int) -> list[EvidenceNote]:
    filtered = [note for note in notes if _is_high_value_note(note)]
    return filtered[:max_notes]


def _dedupe_notes(notes: list[EvidenceNote], max_notes: int) -> list[EvidenceNote]:
    """Drop near-duplicate notes and keep only the top N."""
    deduped: list[EvidenceNote] = []
    seen: set[tuple[str, str]] = set()

    for note in notes:
        key = (note.source_url.strip().lower(), note.key_point.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(note)

        if len(deduped) >= max_notes:
            break

    return deduped


def extract_evidence_for_subquestion(
    subquestion: str,
    search_results: list[SearchResult],
    max_notes: int = 4,
) -> list[EvidenceNote]:
    """
    Extract the strongest evidence notes for one subquestion.

    The model is grounded only in the provided search results.
    """
    if not search_results:
        return []

    llm = ChatOpenAI(model="gpt-4o-mini")
    extractor_llm = llm.with_structured_output(EvidenceNoteList)

    serialized_results = json.dumps(
        [result.model_dump() for result in search_results],
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""
You are an evidence extraction assistant for a research workflow.

Task:
- Read the subquestion and provided search results.
- Extract only high-value, non-duplicative evidence notes.
- Use only the provided search results. Do not use outside knowledge.
- Ignore irrelevant, weak, or generic snippets.
- Each note must map to one source title + one source URL.
- Keep key_point concise and evidence compact.
- Only extract evidence that is specific and useful for technical analysis.
- Prefer evidence with:
  - quantitative details (numbers, costs, latency, token usage)
  - explicit comparisons (for example, "RAG is faster than long-context because ...")
  - concrete claims that can support an argument
- Avoid evidence that is:
  - vague summaries
  - generic statements like "this can be useful"
  - filler or purely descriptive text
- If a snippet does NOT contain strong, specific, or comparative evidence, DO NOT extract a note.

Comparison guidance:
- Prefer evidence that directly compares the approaches in the query.
- If a snippet discusses only one method, extract it only when it contains strong quantitative or technical insight.
- Otherwise skip it.

Subquestion:
{subquestion}

Search results (JSON):
{serialized_results}

Output requirements:
- Return at most {max_notes} notes.
- Returning fewer notes (including zero) is better than returning weak notes.
- Return structured notes only for downstream report generation.
- Do not speculate beyond the provided snippets.
""".strip()

    try:
        extracted = extractor_llm.invoke(prompt)
    except Exception as exc:
        raise RuntimeError(f"Failed to extract evidence for subquestion: {subquestion}") from exc

    normalized_notes = [
        note.model_copy(update={"subquestion": subquestion}) for note in extracted.notes
    ]
    filtered_notes = _filter_high_value_notes(normalized_notes, max_notes=max_notes)
    return _dedupe_notes(filtered_notes, max_notes=max_notes)


def run_extractor(
    grouped_results: dict[str, list[SearchResult]],
    max_notes_per_subquestion: int = 4,
) -> dict[str, list[EvidenceNote]]:
    """Run evidence extraction over every subquestion's search results."""
    items = list(grouped_results.items())
    if not items:
        return {}

    print(f"Running extraction for {len(items)} subquestions in parallel")

    # Extractions are independent and mostly network-bound model calls.
    max_workers = min(8, len(items))
    grouped_notes: dict[str, list[EvidenceNote]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for subquestion, notes in executor.map(
            _extract_one_subquestion,
            items,
            [max_notes_per_subquestion] * len(items),
        ):
            grouped_notes[subquestion] = notes

    return grouped_notes


def identify_failed_subquestions(
    grouped_results: dict[str, list[SearchResult]],
    grouped_notes: dict[str, list[EvidenceNote]],
    ordered_subquestions: list[str] | None = None,
) -> list[str]:
    """
    Mark subquestions that still need research support.

    A subquestion is considered failed when it has no search results or no extracted notes.
    """
    subquestions = (
        ordered_subquestions
        if ordered_subquestions is not None
        else list(grouped_results.keys())
    )

    failed_subquestions: list[str] = []
    for subquestion in subquestions:
        if not grouped_results.get(subquestion) or not grouped_notes.get(subquestion):
            failed_subquestions.append(subquestion)

    return failed_subquestions


def _extract_one_subquestion(
    item: tuple[str, list[SearchResult]],
    max_notes: int,
) -> tuple[str, list[EvidenceNote]]:
    subquestion, results = item
    try:
        notes = extract_evidence_for_subquestion(
            subquestion=subquestion,
            search_results=results,
            max_notes=max_notes,
        )
    except Exception:
        # Keep pipeline moving if one extraction step fails.
        notes = []
    return subquestion, notes


def save_evidence_notes(
    grouped_notes: dict[str, list[EvidenceNote]],
    output_path: str | Path | None = None,
) -> Path:
    """Persist extracted evidence notes for easy inspection."""
    if output_path is None:
        output_path = Path(__file__).resolve().parent / "outputs" / "notes.json"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        subquestion: [note.model_dump() for note in notes]
        for subquestion, notes in grouped_notes.items()
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
