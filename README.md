<pre style="background:#000;color:#fff;padding:12px;border-radius:6px;">
                                   _                 
 _ __ ___  ___  ___  __ _ _ __ ___| |__    _     _   
| '__/ _ \/ __|/ _ \/ _` | '__/ __| '_ \ _| |_ _| |_ 
| | |  __/\__ \  __/ (_| | | | (__| | | |_   _|_   _|
|_|  \___||___/\___|\__,_|_|  \___|_| |_| |_|   |_|  
                                                     
</pre>

# researchpp

`researchpp` is a staged, retrieval-grounded research pipeline that generates markdown reports from a user query.

It decomposes a question into subquestions, retrieves web evidence, extracts structured notes, writes a synthesis, and runs a reviewer pass that can trigger one bounded retry.

## What It Does

Given a query, the app runs this pipeline:

1. Plan: turn the query into a research goal, subquestions, and report outline.
2. Search: retrieve results for each subquestion (in parallel).
3. Extract: convert snippets into high-value structured evidence notes (in parallel).
4. Write: generate a markdown report grounded in extracted notes.
5. Review: evaluate report support quality and optionally trigger one retry path.

Outputs are persisted at each stage for inspection and debugging.

## Architecture

The workflow is orchestrated with LangGraph and a shared typed state object.

```text
START
  -> planner
  -> searcher
  -> extractor
  -> writer
  -> reviewer
      -> approved -> END
      -> failed (max retries reached) -> END
      -> retry_search -> prepare_retry -> searcher
      -> retry_write  -> prepare_retry -> writer
```

Core orchestration lives in `workflow.py`:

- `ResearchWorkflowState`: typed cross-node state contract.
- Node functions (`_planner_node`, `_searcher_node`, etc.) update partial state.
- Conditional routing after review determines retry behavior.

### Parallelism Model

- Graph topology is unchanged: `planner -> searcher -> extractor -> writer -> reviewer`.
- Parallelism is internal to stage implementations, not graph nodes:
  - `searcher.py`: subquestion searches run concurrently via `ThreadPoolExecutor`.
  - `extractor.py`: per-subquestion evidence extraction runs concurrently via `ThreadPoolExecutor`.
- Why this is safe:
  - each subquestion is independent in search and extraction
  - these calls are I/O-bound (web + model API latency), so threads reduce wall-clock time
- Failure isolation is preserved:
  - search failure for one subquestion -> `[]` for that subquestion
  - extraction failure for one subquestion -> `[]` for that subquestion
- Output schemas and artifact formats are unchanged.

## Project Structure

```text
researchpp/
├── main.py            # Typer CLI entrypoint
├── workflow.py        # LangGraph orchestration + routing
├── schemas.py         # Pydantic contracts between stages
├── planner.py         # Query -> ResearchPlan
├── searcher.py        # Tavily retrieval + normalization
├── extractor.py       # Evidence extraction + filtering/dedup
├── writer.py          # Report synthesis + deterministic sources section
├── reviewer.py        # Structured quality review + retry signals
├── research           # Bash launcher (`uv run python main.py`)
└── outputs/           # Persisted artifacts (json + markdown)
```

## Data Contracts (Schemas)

Defined in `schemas.py`:

- `ResearchPlan`
  - `research_goal`
  - `subquestions[]`
  - `report_outline[]`
- `SearchResult`
  - `title`, `url`, `snippet`
- `EvidenceNote`
  - `subquestion`, `source_title`, `source_url`
  - `key_point`, `evidence`, `relevance_reason`
  - optional `confidence_score` in `[0.0, 1.0]`
- `ReviewDecision`
  - `approved`, `needs_more_research`
  - `overall_assessment`
  - `support_gaps[]`, `revision_instructions[]`, `weak_sections[]`

LLM stages use structured outputs to enforce these contracts.

## Dependencies

From `pyproject.toml`:

- Python `>=3.13`
- `langgraph`
- `langchain` / `langchain-openai`
- `langchain-tavily` / `tavily-python`
- `rich`
- `pyfiglet`
- `typer`
- `python-dotenv`

## Setup

From the project root:

```bash
cd researchpp
uv sync
```

Create `.env` with required keys:

```bash
OPENAI_API_KEY=...
TAVILY_API_KEY=...
```

`main.py` calls `load_dotenv()`, so these are read automatically at runtime.

## Running

Use the bash wrapper:

```bash
./research "Your research question here"
```

Or call the CLI directly:

```bash
uv run python main.py "Your research question here"
```

### CLI Options

```text
query (positional): user research query
--max-results INTEGER: top results per subquestion (min 1, default 5)
--max-notes INTEGER: max extracted notes per subquestion (min 1, default 4)
--report-title TEXT: optional report title
--report-output TEXT: optional custom markdown output path
--max-retries INTEGER: reviewer-triggered retry passes (0 or 1, default 1)
```

## Stage Details

### Planner (`planner.py`)

- Uses `ChatOpenAI(model="gpt-4o-mini")`.
- Produces validated `ResearchPlan`.

### Searcher (`searcher.py`)

- Uses Tavily (`langchain_tavily.TavilySearch`).
- Runs all subquestion searches concurrently with `ThreadPoolExecutor`.
- Normalizes response shape into `SearchResult`.
- If one subquestion search fails, that subquestion gets an empty list so pipeline continues.

### Extractor (`extractor.py`)

- Structured extraction into `EvidenceNoteList`.
- Runs per-subquestion extraction concurrently with `ThreadPoolExecutor`.
- Applies deterministic post-filters for signal quality:
  - rejects short/vague/generic notes
  - prefers quantitative/comparative/mechanistic evidence
- Deduplicates notes by `(source_url, key_point)`.

### Writer (`writer.py`)

- Synthesizes markdown from plan + notes only.
- Includes strict grounding instructions in prompt.
- On retry passes, consumes reviewer guidance (`revision_instructions`, `weak_sections`).
- Strips any model-generated `## Sources` and appends deterministic source list from notes.

### Reviewer (`reviewer.py`)

- Structured quality gate (`ReviewDecision`).
- Evaluates report support against extracted notes only.
- Signals whether to retry search or rewrite.

## Outputs

Artifacts are written to `outputs/`:

- `search_results.json`: grouped normalized search results.
- `notes.json`: grouped extracted evidence notes.
- `report.md`: first-pass report (default naming).
- `revised_report.md`: retry-pass report (default naming).
- `review.json`: latest reviewer decision and retry count.
- `final_report.md`: stable final artifact pointer written at end of workflow.

Even when naming differs via `--report-output`, `final_report.md` is still written for a stable final location.

## Failure Behavior and Retry Semantics

- Planner, writer, reviewer raise `RuntimeError` on stage failure.
- Search and extraction are fault-tolerant per subquestion and continue with empty lists on failures.
- Retry loop is bounded:
  - reviewer approves -> workflow ends
  - reviewer requests retry and retry budget remains -> one retry path executes
  - retry budget exhausted -> workflow ends with latest report

## Design Notes

- The system is intentionally modular: each stage has one clear responsibility.
- Structured schemas reduce free-form LLM drift between stages.
- Persisted intermediate artifacts make outputs explainable and debuggable.
- Stages run in sequence, but search and extraction fan out subquestion work in parallel for latency reduction.
