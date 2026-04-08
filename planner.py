from langchain_openai import ChatOpenAI

from schemas import ResearchPlan


def generate_research_plan(query: str) -> ResearchPlan:
    """Generate a validated research plan for a user query."""
    llm = ChatOpenAI(model="gpt-4o-mini")
    planner_llm = llm.with_structured_output(ResearchPlan)

    prompt = f"""
You are a research planning assistant.

Given the user query below, return a structured research plan.

Requirements:
1. Rewrite the query into a clear research goal.
2. Generate 3 to 5 focused subquestions.
3. Generate a simple report outline as a short list of sections.

User query: {query}
""".strip()

    try:
        return planner_llm.invoke(prompt)
    except Exception as exc:
        # Keep planner errors explicit for the CLI layer.
        raise RuntimeError(f"Failed to generate a structured research plan: {exc}") from exc
