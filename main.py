from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import typer

app = typer.Typer(add_completion=False)


@app.command()
def main(query: str) -> None:
    load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

    print(f"Query: {query}")

    llm = ChatOpenAI(model="gpt-4o-mini")
    response = llm.invoke(query)

    print(f"Response: {response.content}")


if __name__ == "__main__":
    app()
