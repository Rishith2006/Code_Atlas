# CodeAtlas — AI Codebase Investigator

Upload a Python project (`.zip`) and CodeAtlas parses it, scores risky
functions, maps call flows, generates documentation, and answers questions
about the code — every answer linked to real `file:line` locations.

## Features

| Feature (from spec) | Implementation |
|---|---|
| ZIP upload | Web UI + zip-slip-safe extraction |
| Python parser | `codeatlas/parser.py` — stdlib `ast`: functions, classes, imports, call sites |
| Application overview | `codeatlas/llm.py` — LLM or heuristic project summary |
| Project report | `codeatlas/reports.py` — downloadable Markdown report |
| AI summarization | Pluggable OpenAI-compatible LLM, offline heuristic fallback |
| Function optimality | `codeatlas/analysis.py` — complexity/LOC/nesting/param hints |
| Risk score engine | 0–100 score: complexity 35 + LOC 20 + fan-out 15 + fan-in 10 + docs 10 + nesting 10 |
| Flow-to-function nav | `codeatlas/graph.py` — call graph, callers/callees, path tracing, entry points |
| AI project explorer | `codeatlas/chatbot.py` — Q&A (`explain`, `who calls`, `trace a to b`, `riskiest`, `overview`) |

## Quick start

```bash
cd codeatlas
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Web UI (upload zips, explore, chat, download reports)
.venv/bin/python -m codeatlas.cli serve --port 5000
# → http://127.0.0.1:5000  (or click "Load the demo project")

# CLI
.venv/bin/python -m codeatlas.cli analyze ./sample_project --deps
.venv/bin/python -m codeatlas.cli report ./sample_project -o report.md
.venv/bin/python -m codeatlas.cli chat ./sample_project
```

## LLM summaries (optional)

Without a key everything works offline with heuristic summaries. For
LLM-powered explanations set:

```bash
export OPENAI_API_KEY=sk-...
# optional: OPENAI_BASE_URL (any OpenAI-compatible endpoint), CODEATLAS_MODEL
```

## Project layout

```
codeatlas/
  codeatlas/
    parser.py    # AST parsing → Project/Module/Function/Class model
    analysis.py  # cyclomatic complexity, risk scores, optimality hints
    graph.py     # call graph, module deps, path tracing
    llm.py       # summarizer (LLM + offline fallback)
    chatbot.py   # rule-based Q&A with file:line citations
    reports.py   # Markdown report generator
    app.py       # Flask web app + JSON API
    cli.py       # analyze / report / chat / serve commands
  templates/     # index + project explorer pages
  static/        # style.css, app.js
  sample_project/# demo pipeline project (has a deliberately smelly function)
  uploads/       # extracted user projects (created at runtime)
```

## API

- `GET /api/<id>/overview` — stats, modules, riskiest functions, entry points
- `GET /api/<id>/search?q=` — function search
- `GET /api/<id>/function?name=` — detail + summary + callers/callees + flows
- `GET /api/<id>/trace?from=&to=` — call paths between functions
- `POST /api/<id>/chat` `{"question": "..."}` — codebase Q&A
- `GET /api/<id>/report` — Markdown report download

## Deploy on Vercel

The repo ships Vercel-ready: `vercel.json` + `api/index.py` expose the Flask
app as a serverless function, and uploads automatically go to `/tmp` when
`VERCEL` is set.

```bash
cd codeatlas
git init && git add . && git commit -m "CodeAtlas"
# push to a GitHub repo, then:
# vercel.com → Add New Project → import the repo → Deploy
```

Or from the terminal (inside the folder):

```bash
npm i -g vercel
vercel --prod
```

No environment variables are required. Set `OPENAI_API_KEY` in the Vercel
dashboard (Settings → Environment Variables) for LLM-powered summaries.

**Vercel caveats (worth knowing for your report):**
- `/tmp` is ephemeral and not shared between serverless instances — fine for
  demo/class use, but an uploaded project can 404 if traffic fans out across
  instances. For a production deployment use Render/Railway/Fly.io instead
  (persistent disk, no changes needed — just run `codeatlas.cli serve`).
- Keep uploaded zips small (a few MB); serverless functions have tight
  execution time limits, and parsing is done per cold start.

## Notes & limits

- Python-only analysis (per project scope); syntax-broken files are skipped.
- Call resolution is heuristic (name-based); dynamic calls (`getattr`, etc.) aren't traced.
- Uploaded code stays local in `uploads/`; nothing is sent anywhere unless you set an LLM key.
