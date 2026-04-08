import json
from pathlib import Path

from langchain_openai import ChatOpenAI

from schemas import EvidenceNote, ResearchPlan


def _collect_unique_sources(
    extracted_notes: dict[str, list[EvidenceNote]],
) -> list[tuple[str, str]]:
    """Collect and deduplicate sources from extracted evidence notes."""
    sources: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for notes in extracted_notes.values():
        for note in notes:
            url = note.source_url.strip()
            if not url:
                continue

            normalized_url = url.lower()
            if normalized_url in seen_urls:
                continue

            seen_urls.add(normalized_url)
            title = note.source_title.strip() or "Untitled Source"
            sources.append((title, url))

    return sources


def _build_sources_markdown(sources: list[tuple[str, str]]) -> str:
    """Render a simple markdown source list."""
    if not sources:
        return "- No sources available from extracted evidence notes."

    return "\n".join(f"- {title} — {url}" for title, url in sources)


def _strip_sources_section(markdown: str) -> str:
    """Remove any model-generated Sources section so we can append a deterministic one."""
    marker = "\n## Sources"
    index = markdown.find(marker)
    if index == -1:
        return markdown.strip()
    return markdown[:index].strip()


def generate_report(
    plan: ResearchPlan,
    extracted_notes: dict[str, list[EvidenceNote]],
    report_title: str | None = None,
    revision_instructions: list[str] | None = None,
    weak_sections: list[str] | None = None,
) -> str:
    """
    Generate a markdown report from structured plan + evidence notes.

    This stage synthesizes evidence; it does not perform retrieval.
    """
    title = report_title or "Research Report"
    sources = _collect_unique_sources(extracted_notes)
    sources_markdown = _build_sources_markdown(sources)

    flattened_notes = [
        note for notes_for_subquestion in extracted_notes.values() for note in notes_for_subquestion
    ]
    if not flattened_notes:
        return (
            f"# {title}\n\n"
            "## Research Goal\n"
            f"{plan.research_goal}\n\n"
            "## Executive Summary\n"
            "No extracted evidence notes were available, so a grounded synthesis could not be generated.\n\n"
            "## Key Findings\n"
            "No evidence-backed findings are available yet.\n\n"
            "## Analysis / Technical Takeaways\n"
            "Further evidence extraction is needed before technical takeaways can be finalized.\n\n"
            "## Open Questions / Limitations\n"
            "- No evidence notes were provided to the writer stage.\n"
            "- Conclusions should not be treated as complete.\n\n"
            "## Sources\n"
            f"{sources_markdown}\n"
        )

    llm = ChatOpenAI(model="gpt-4o-mini")
    notes_payload = {
        subquestion: [note.model_dump(exclude_none=True) for note in notes]
        for subquestion, notes in extracted_notes.items()
    }

    revision_guidance_block = ""
    if revision_instructions or weak_sections:
        revision_guidance_block = f"""
Retry revision guidance:
- This is a reviewer-requested revision pass.
- Address the revision instructions and weak sections explicitly.
- Prioritize stronger grounding and clarity in the flagged areas.

Revision instructions (JSON):
{json.dumps(revision_instructions or [], indent=2, ensure_ascii=False)}

Weak sections (JSON):
{json.dumps(weak_sections or [], indent=2, ensure_ascii=False)}
""".strip()

    prompt = f"""
You are writing a final research report in markdown.

Context:
- This is the synthesis stage after planning, search, and extraction.
- The extracted evidence notes are the source of truth.
- Do not retrieve new information and do not use outside knowledge.

Instructions:
1. Use the research goal and evidence notes to produce a clear, professional report with specific claims.
2. Use strong, specific claims only when directly supported by evidence notes.
3. Do not use vague modal phrasing such as "may", "can", or "tends to".
4. For comparative topics, explicitly compare approaches in each key section.
5. In Key Findings, present side-by-side subsections for Cost, Latency, and Answer Quality using this format:
   - RAG: ...
   - Long-context: ...
   - Tradeoff: ...
6. Ground claims with concrete details from evidence notes (numbers, comparisons, mechanisms) instead of generic statements.
7. If evidence is weak or missing for a point, explicitly state: "Insufficient evidence in snippets to conclude."
8. If strong quantitative or comparative evidence is missing:
   - explicitly state the limitation
   - do NOT generalize
   - do NOT infer
   - Example: "Available sources do not provide direct cost benchmarks, limiting quantitative comparison between RAG and long-context approaches."
9. Synthesize findings; do not copy notes verbatim and do not repeat the same point.
10. Output markdown only.
11. Include these sections:
   - # {title}
   - ## Research Goal
   - ## Executive Summary
   - ## Key Findings
   - ## Analysis / Technical Takeaways
   - ## Open Questions / Limitations
12. Do not include a Sources section; it will be appended separately.

Research plan (JSON):
{json.dumps(plan.model_dump(), indent=2, ensure_ascii=False)}

Extracted evidence notes grouped by subquestion (JSON):
{json.dumps(notes_payload, indent=2, ensure_ascii=False)}

{revision_guidance_block}
""".strip()

    try:
        report_body = llm.invoke(prompt).content
    except Exception as exc:
        raise RuntimeError("Failed to generate report from extracted evidence notes.") from exc

    cleaned_body = _strip_sources_section(str(report_body))
    return f"{cleaned_body}\n\n## Sources\n{sources_markdown}\n"


def save_report(markdown_report: str, output_path: str | Path | None = None) -> Path:
    """Save the final markdown report to disk."""
    if output_path is None:
        output_path = Path(__file__).resolve().parent / "outputs" / "report.md"

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_report, encoding="utf-8")
    return path
