# DataFlow

Upload a CSV, get a health check: missing values (including "N/A"/"unknown"/"-"), duplicates, outliers,
inconsistent formats, impossible values, mixed types, merged-cell leftovers, and broken relationships
between columns. It then proposes safe fixes that you approve or reject; nothing changes without your say-so,
every change is logged, and everything can be undone.

## Run it
```
pip install -r requirements.txt
streamlit run app.py
```
Click "Try the sample dataset" in the sidebar to see it work on fake NHS-style appointments data.

## Run it without the terminal
Double-click `run_local.bat` (Windows) or `run_local.command` (Mac). The first run sets up a private Python
environment and installs everything; after that it just starts the app.

## Put it online (Railway)
1. Create a GitHub repository and upload this folder (the `.gitignore` keeps junk out).
2. On railway.app choose New Project, then Deploy from GitHub repo, and pick it. Railway finds the `Dockerfile`
   and `railway.json` by itself.
3. In the service's Settings, click Generate Domain. That link is your public app.
4. Do not add an `ANTHROPIC_API_KEY` variable. The container runs in public mode (`DATAFLOW_PUBLIC=1`), which
   ignores any server key, so visitors use demo mode or paste their own key and nobody spends your credits.

Public mode also limits files to 25 MB and 50,000 rows (`DATAFLOW_MAX_ROWS` changes the row limit), forgets uploaded
data after about 15 minutes, and shows a "don't upload confidential data" notice. Nothing is written to disk.

Free alternative: Streamlit Community Cloud (share.streamlit.io). Point it at the repo with `app.py` as the main file
and add `DATAFLOW_PUBLIC = "1"` under Settings, Secrets/Environment.

If file uploads fail with a 403 error behind a proxy, set `STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false`.

## AI review (optional)
Paste a Claude API key in the sidebar (or set `ANTHROPIC_API_KEY`) to get suggestions from Claude for the things
rules can't settle: nicknames and typos in categories, numbers written as text, and impossible or extreme values.
Without a key the tab runs in a clearly-labelled demo mode that uses a few fixed rules instead of AI.
Only column summaries and the unusual values are sent (the tab shows exactly what, before anything is sent), the AI
never edits data directly, and every reply is checked by code before it becomes a suggestion you can approve.

## Layout
- `dataflow/profiler.py`: the checking engine (finds problems). No UI code.
- `dataflow/fixer.py`: proposes fixes and applies only the approved ones, producing a change log.
- `dataflow/ai.py`: the AI review layer (Claude client, offline demo client, validation of every reply).
- `dataflow/reporting.py`: before/after comparison and the Markdown report.
- `app.py`: Streamlit interface (Issues, Fix, AI review, Results, Columns, Data preview).
- `make_test_data.py`: builds a messy dataset with planted errors and `ground_truth.json`.
- `evaluate.py`: scores the engine against the planted errors. `python evaluate.py`
- `Dockerfile`, `railway.json`, `.streamlit/config.toml`: hosting. `run_local.*`: double-click launchers.
- `tests/`: `python -m pytest tests -q`

## Roadmap
1. Profiling (done)  2. Rule-based fixes with approve/reject, undo, cleaned export and report (done)
3. AI review for judgement calls, with summary (done; typos/nicknames, text numbers, extreme values)
4. Not built yet: AI explanations for broken date relationships, AI fills for missing values, ambiguous dates
5. Hosted deployment files (done)
6. Optional Next.js + Python API front end
