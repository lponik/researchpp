import json
from pathlib import Path

from langchain_openai import ChatOpenAI

from schemas import EvidenceNote, EvidenceNoteList, SearchResult


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
- Extract the strongest, non-duplicative evidence notes.
- Use only the provided search results. Do not use outside knowledge.
- Ignore irrelevant or weak snippets.
- Each note must map to one source title + one source URL.
- Keep key_point concise and evidence compact.

Subquestion:
{subquestion}

Search results (JSON):
{serialized_results}

Output requirements:
- Return at most {max_notes} notes.
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
    return _dedupe_notes(normalized_notes, max_notes=max_notes)


def run_extractor(
    grouped_results: dict[str, list[SearchResult]],
    max_notes_per_subquestion: int = 4,
) -> dict[str, list[EvidenceNote]]:
    """Run evidence extraction over every subquestion's search results."""
    grouped_notes: dict[str, list[EvidenceNote]] = {}
    for subquestion, results in grouped_results.items():
        try:
            grouped_notes[subquestion] = extract_evidence_for_subquestion(
                subquestion=subquestion,
                search_results=results,
                max_notes=max_notes_per_subquestion,
            )
        except RuntimeError:
            # Keep pipeline moving if one extraction step fails.
            grouped_notes[subquestion] = []

    return grouped_notes


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
