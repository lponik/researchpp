from dotenv import load_dotenv
load_dotenv()

import typer

from reviewer import summarize_review_decision
from workflow import run_research_workflow

app = typer.Typer(add_completion=False)


@app.command()
def main(
    query: str,
    max_results: int = typer.Option(5, min=1, help="Top results per subquestion."),
    max_notes: int = typer.Option(
        4, min=1, help="Max extracted evidence notes per subquestion."
    ),
    report_title: str | None = typer.Option(None, help="Optional report title."),
    report_output: str | None = typer.Option(
        None, help="Optional output path for the markdown report."
    ),
    max_retries: int = typer.Option(
        1, min=0, max=1, help="Maximum number of reviewer-triggered retry passes."
    ),
) -> None:
    try:
        state = run_research_workflow(
            user_query=query,
            max_results=max_results,
            max_notes=max_notes,
            report_title=report_title,
            report_output=report_output,
            max_retries=max_retries,
        )
    except RuntimeError as exc:
        typer.secho(f"Workflow error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"Unexpected workflow failure: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    plan = state["plan"]
    grouped_results = state["search_results"]
    grouped_notes = state["extracted_notes"]
    review = state["review_decision"]

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

    print()
    print("Search Results Summary:")
    for subquestion, results in grouped_results.items():
        print(f"- {subquestion} ({len(results)} results)")
    print()
    print(f"Saved raw search results to: {state.get('search_results_path')}")

    print()
    print("Evidence Notes Summary:")
    for subquestion, notes in grouped_notes.items():
        print(f"- {subquestion} ({len(notes)} notes)")
    print()
    print(f"Saved extracted evidence notes to: {state.get('notes_output_path')}")

    print()
    print("Review Decision:")
    print(summarize_review_decision(review))
    print(f"Retry triggered: {state.get('retry_triggered', False)}")
    print(f"Retry count: {state.get('retry_count', 0)} / {max_retries}")
    print()
    print(f"Saved review decision to: {state.get('review_output_path')}")
    print(f"Saved latest report artifact to: {state.get('report_output_path')}")
    print(f"Saved final markdown report to: {state.get('final_report_path')}")


if __name__ == "__main__":
    app()
