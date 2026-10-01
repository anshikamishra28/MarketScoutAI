# MarketScoutAI

MarketScoutAI is a modular market research prototype. It turns a research question into a bounded web research run, retains source metadata and verbatim evidence, tracks coverage gaps, and produces a cited report through a FastAPI API and Next.js dashboard.

## Problem and approach

Market research often combines scattered public sources and leaves readers unable to trace conclusions. MarketScoutAI uses a plan–search–fetch–evaluate–follow-up loop so coverage gaps can drive another search iteration. Gemini creates a structured plan when configured; source collection, budget enforcement, evidence checks, gap checks, conflict flags, persistence, and report assembly are explicit code. If Gemini is unavailable, a deterministic plan keeps the web research flow available.

## Architecture

```text
Next.js dashboard → FastAPI → research executor
                               ├─ planner → Gemini (optional)
                               ├─ Google News RSS search
                               ├─ HTTP fetcher → HTML text extraction
                               ├─ evidence/source evaluation and gap/conflict checks
                               └─ SQLite: runs, sources, evidence, reports
```

### Research loop and budgets

The planner records a goal, sub-questions, information requirements, and initial queries. For up to 3 iterations, the executor searches, deduplicates URLs and query tasks, fetches pages, evaluates page scope and source type, and extracts verbatim sentences from usable article pages. Unanswered requirements create targeted follow-up queries. The run stops on sufficient keyword coverage, exhausted queries, or the 15-unique-source cap. Fetch/search failures are recorded or skipped and do not fabricate article evidence.

Coverage matching, source confidence, recency, geographic relevance, and numeric conflict detection are heuristics, not external credibility data or independent verification. Evidence usefulness combines source class, publication date, topical relevance, geographic fit, and an exact-text support check. Unknown publishers remain eligible but score below recognized source classes. Evidence is only extracted from fetched `source_page` content; snippets, Google News wrappers, empty pages, publisher homepages, incomplete statements, and obvious editorial copy are not treated as evidence. Candidate selection limits repeated claims from one source or publisher while favoring uncovered requirements.

### Evidence and persistence

Evidence records include IDs, run/source IDs, claim text, exact supporting text, source URL/title/publisher/date/type, content scope, relevance, confidence, and extraction timestamp. SQLite uses the standard library and creates `database/market_scout.sqlite3` by default. Set `MARKETSCOUT_DB` to use another location. The tables are `research_runs`, `sources`, `evidence`, and `reports`.

### API

Run the API at `http://localhost:8000`; interactive OpenAPI docs are at `/docs`.

| Method | Endpoint | Behavior |
|---|---|---|
| POST | `/research` | Queues a run and returns its ID (HTTP 202) |
| GET | `/research/{id}` | Run, activity, evidence, and report metadata |
| GET | `/research/{id}/status` | Current status and progress activity |
| GET | `/research/{id}/sources` | Source metadata and extracted evidence |
| GET | `/research/{id}/report` | Completed Markdown report |
| GET | `/health` | Health check |

The current API runs work through FastAPI background tasks in the API process. For multi-worker production deployment, replace this with a durable task queue. Requirement coverage is labeled sufficient, weak, or unanswered by a keyword heuristic.

## Frontend

The Next.js app in `frontend/` provides a research prompt, run progress, coverage metrics, cited report, and evidence ledger. It expects the API on `http://localhost:8000` by default; override with `NEXT_PUBLIC_API_URL` in the frontend environment.

## Setup

Python 3.10+ and Node.js 20+ are recommended. No paid services are required. Google News RSS and public webpages are used without credentials; Gemini is optional.

1. Create and activate a Python virtual environment.
2. Install Python dependencies: `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env`. `GEMINI_API_KEY` and `GEMINI_MODEL` enable Gemini planning; `SEARX_URL` optionally configures a SearXNG search endpoint. `MARKETSCOUT_DB` changes the SQLite file location. Keep `.env` private; it is ignored by Git.
4. Start the API: `python run.py`.
5. In another terminal: `cd frontend`, `npm install`, `npm run dev`.
6. Open `http://localhost:3000`.

Example research questions:

- Analyze the Indian smartphone market under ₹30,000.
- What are the main competitors and consumer trends in India's electric two-wheeler market?
- Compare pricing and market positioning for affordable skincare brands in India.

## Testing

Run the deterministic unit/API suite with `python -m unittest discover -s tests -v`. The root `test_*.py` files are legacy interactive smoke scripts and some call external services; they are not part of this offline suite. A real research run requires network access and may benefit from a valid Gemini key. Run it from the dashboard or use:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/research -ContentType 'application/json' -Body '{"question":"Analyze the Indian smartphone market under ₹30,000"}'
```

## Limitations and next steps

- Search currently uses Google News RSS and can miss direct evergreen sources.
- Direct Bing/Google/SearXNG search is attempted first, but providers may block automated requests; wrapper-only results are retained as search leads and correctly produce no article evidence.
- Fetching is limited to public HTML pages; paywalls, JavaScript-only pages, and access controls may prevent extraction.
- Source categories and confidence, information coverage, and conflicts use basic heuristics. The report presents evidence rather than claiming exhaustive market sizing.
- Background work is process-local; there is no authentication, user management, or deployment configuration.
- Useful next steps are broader free search providers, stronger requirement-to-evidence evaluation, reviewed conflict resolution, and a durable task queue.
