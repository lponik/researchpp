from pathlib import Path

from dotenv import load_dotenv
import typer

from extractor import run_extractor, save_evidence_notes
from planner import generate_research_plan
from searcher import run_searcher, save_search_results
from writer import generate_report, save_report

app = typer.Typer(add_completion=False)


@app.command()
def main(
    query: str,
    max_results: int = typer.Option(3, min=1, help="Top results per subquestion."),
    max_notes: int = typer.Option(
        4, min=1, help="Max extracted evidence notes per subquestion."
    ),
    report_title: str | None = typer.Option(None, help="Optional report title."),
    report_output: str | None = typer.Option(
        None, help="Optional output path for the markdown report."
    ),
) -> None:
    # Load environment variables for OpenAI credentials.
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    try:
        plan = generate_research_plan(query)
    except RuntimeError as exc:
        typer.secho(f"Planner error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    print("Research Goal:")
    print(plan.research_goal)
    print()
    print("Subquestions:")
    for item in plan.subquestions:
        print(f"- {item}")
    print()
    print("Report Outline:")
    for section in plan.report_outline:
        print(f"- {section}")

    grouped_results = run_searcher(plan=plan, max_results=max_results)
    output_path = save_search_results(grouped_results)
    print()
    print("Search Results Summary:")
    for subquestion, results in grouped_results.items():
        print(f"- {subquestion} ({len(results)} results)")
    print()
    print(f"Saved raw search results to: {output_path}")

    grouped_notes = run_extractor(
        grouped_results=grouped_results,
        max_notes_per_subquestion=max_notes,
    )
    notes_output_path = save_evidence_notes(grouped_notes)
    print()
    print("Evidence Notes Summary:")
    for subquestion, notes in grouped_notes.items():
        print(f"- {subquestion} ({len(notes)} notes)")
    print()
    print(f"Saved extracted evidence notes to: {notes_output_path}")

    try:
        markdown_report = generate_report(
            plan=plan,
            extracted_notes=grouped_notes,
            report_title=report_title,
        )
    except RuntimeError as exc:
        typer.secho(f"Writer error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    report_path = save_report(markdown_report=markdown_report, output_path=report_output)
    print()
    print(f"Saved final markdown report to: {report_path}")


if __name__ == "__main__":
    app()
