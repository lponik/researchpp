from dotenv import load_dotenv

load_dotenv()

import typer
from typing import Any

from reviewer import summarize_review_decision
from workflow import run_research_workflow

try:
    from pyfiglet import Figlet
except Exception:  # pragma: no cover - graceful fallback when dependency is missing
    Figlet = None  # type: ignore[assignment]

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
except Exception:  # pragma: no cover - graceful fallback when dependency is missing
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]

app = typer.Typer(add_completion=False)
console = Console() if Console else None

ASCII_BANNER = r"""
                                   _                 
 _ __ ___  ___  ___  __ _ _ __ ___| |__    _     _   
| '__/ _ \/ __|/ _ \/ _` | '__/ __| '_ \ _| |_ _| |_ 
| | |  __/\__ \  __/ (_| | | | (__| | | |_   _|_   _|
|_|  \___||___/\___|\__,_|_|  \___|_| |_| |_|   |_|  
                                                     
                                                        
""".strip("\n")




def _rich_enabled() -> bool:
    return bool(console and getattr(console, "is_terminal", False))


def print_banner() -> None:
    subtitle = "Staged research pipeline: planner -> searcher -> extractor -> writer -> reviewer"

    if not _rich_enabled():
        print("research++")
        print(subtitle)
        print()
        return

    art = ASCII_BANNER
    if Figlet:
        try:
            art = Figlet(font="standard", width=120).renderText("research++").rstrip()
        except Exception:
            art = ASCII_BANNER

    banner_text = Text(art, style="bold cyan")
    console.print(Panel.fit(banner_text, border_style="bright_blue", padding=(0, 1)))
    console.print("[dim]Fast, retrieval-grounded report generation from a single command.[/dim]")
    console.print(f"[dim]{subtitle}[/dim]")
    console.print()


def _print_workflow_error(message: str) -> None:
    if _rich_enabled():
        console.print(f"[bold red]{message}[/bold red]")
        return
    typer.secho(message, fg=typer.colors.RED, err=True)


def _format_count_block(items: dict[str, list[Any]]) -> str:
    if not items:
        return "- none"
    return "\n".join(f"- {label} ({len(values)})" for label, values in items.items())


def _print_plain_summary(state: dict[str, Any], max_retries: int) -> None:
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


def _print_styled_summary(state: dict[str, Any], max_retries: int) -> None:
    plan = state["plan"]
    grouped_results = state["search_results"]
    grouped_notes = state["extracted_notes"]
    review = state["review_decision"]

    plan_lines = [
        f"[bold]Research Goal[/bold]\n{plan.research_goal}",
        "[bold]Subquestions[/bold]",
        "\n".join(f"- {item}" for item in plan.subquestions) or "- none",
        "[bold]Report Outline[/bold]",
        "\n".join(f"- {section}" for section in plan.report_outline) or "- none",
    ]
    console.print(
        Panel(
            "\n\n".join(plan_lines),
            title="[[plan]] planner",
            border_style="cyan",
        )
    )

    console.print(
        Panel(
            _format_count_block(grouped_results),
            title="[[search]] searcher results",
            border_style="green",
        )
    )
    console.print(
        Panel(
            _format_count_block(grouped_notes),
            title="[[extract]] extractor notes",
            border_style="yellow",
        )
    )

    review_lines = [
        summarize_review_decision(review),
        "",
        f"Retry triggered: {state.get('retry_triggered', False)}",
        f"Retry count: {state.get('retry_count', 0)} / {max_retries}",
    ]
    console.print(
        Panel(
            "\n".join(review_lines),
            title="[[review]] reviewer",
            border_style="magenta",
        )
    )

    paths_lines = [
        f"search results: {state.get('search_results_path')}",
        f"evidence notes: {state.get('notes_output_path')}",
        f"review decision: {state.get('review_output_path')}",
        f"latest report artifact: {state.get('report_output_path')}",
    ]
    console.print(
        Panel(
            "\n".join(paths_lines),
            title="[[write]] outputs",
            border_style="blue",
        )
    )


def print_summary(state: dict[str, Any], max_retries: int) -> None:
    if _rich_enabled():
        _print_styled_summary(state=state, max_retries=max_retries)
        return
    _print_plain_summary(state=state, max_retries=max_retries)


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
    print_banner()

    try:
        if _rich_enabled():
            with console.status(
                "[bold cyan]Running workflow[/bold cyan] [dim][[plan -> search -> extract -> write -> review]][/dim]",
                spinner="dots",
            ):
                state = run_research_workflow(
                    user_query=query,
                    max_results=max_results,
                    max_notes=max_notes,
                    report_title=report_title,
                    report_output=report_output,
                    max_retries=max_retries,
                )
        else:
            print("Running workflow...")
            state = run_research_workflow(
                user_query=query,
                max_results=max_results,
                max_notes=max_notes,
                report_title=report_title,
                report_output=report_output,
                max_retries=max_retries,
            )
    except RuntimeError as exc:
        _print_workflow_error(f"Workflow error: {exc}")
        raise typer.Exit(code=1)
    except Exception as exc:
        _print_workflow_error(f"Unexpected workflow failure: {exc}")
        raise typer.Exit(code=1)

    print_summary(state=state, max_retries=max_retries)


if __name__ == "__main__":
    app()
