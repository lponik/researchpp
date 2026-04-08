from pathlib import Path

from dotenv import load_dotenv
import typer

from planner import generate_research_plan

app = typer.Typer(add_completion=False)


@app.command()
def main(query: str) -> None:
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


if __name__ == "__main__":
    app()
