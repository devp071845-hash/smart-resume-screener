# Smart Resume Screener

Parses resumes (PDF/text), extracts structured candidate data, and uses an LLM
to score how well each candidate fits a job description — with a shortlist
dashboard to review results.

## Architecture

```
                     ┌────────────────────┐
   Browser  ───────▶ │  Flask app (app.py) │
  (dashboard)  ◀───── │  REST API + UI      │
                     └─────────┬───────────┘
                               │
             ┌─────────────────┼──────────────────┐
             ▼                 ▼                   ▼
        parser.py         llm_matcher.py         db.py
     (PDF/text → text)  (extraction & scoring   (SQLite:
                          via Anthropic API)      resumes, JDs,
                                                   matches)
```

- **Backend**: Flask (Python). A single-process REST API + server-rendered
  dashboard, chosen for minimal setup overhead — no build step, no separate
  frontend framework required.
- **Parsing** (`parser.py`): `pdfplumber` extracts text from PDF resumes;
  `.txt` files are read directly. Structured fields (skills, experience,
  education) are **not** regex-extracted here — resume formats vary too much
  for that to be reliable. That job is delegated to the LLM.
- **LLM layer** (`llm_matcher.py`): Two prompts against the Google Gemini API
  (`generateContent`, default model `gemini-2.5-flash`, overridable via
  `GEMINI_MODEL`), called directly over HTTPS with `requests` (no SDK
  dependency):
  1. **Extraction** — resume text → structured JSON (skills, experience,
     education, years of experience).
  2. **Scoring** — resume + job description → 1–10 fit score, justification,
     matched skills, missing skills.

  If `GOOGLE_API_KEY` isn't set, both functions fall back to a small
  heuristic (keyword-overlap) implementation so the app is still fully
  demoable without a key. Fallback results are explicitly tagged
  `"_source": "heuristic_fallback"` in the API response and flagged in the
  UI's justification text — they're never silently presented as LLM output.
- **Storage** (`db.py`): SQLite via the stdlib `sqlite3` module — three
  tables (`job_descriptions`, `resumes`, `matches`). No ORM, to keep the
  dependency footprint small; the schema is simple enough not to need one.
- **Frontend**: One server-rendered page (`templates/index.html` +
  `static/app.js`) — an "intake desk" for filing job descriptions, uploading
  resumes, and running matches, plus a shortlist view sorted by score.

## LLM prompts

**Extraction system prompt** (`llm_matcher.EXTRACTION_SYSTEM_PROMPT`):
instructs the model to act as a resume parsing engine and return only a JSON
object matching a fixed schema (`name`, `skills`, `experience`, `education`,
`total_years_experience`), with nulls for anything it can't determine.

**Scoring prompt** (`llm_matcher.SCORING_SYSTEM_PROMPT` + user message):
follows the brief's example almost verbatim —

> "Compare the following resume with this job description and rate fit on
> 1–10 with justification."

— extended to require structured JSON output (`score`, `justification`,
`matched_skills`, `missing_skills`) and to push the model toward
evidence-based justifications (citing specific resume details) rather than
generic praise.

Both prompts are defined at the top of `llm_matcher.py` and are the first
thing to tune if match quality needs adjusting.

**Model note**: Google periodically retires Gemini model IDs (see the
[changelog](https://ai.google.dev/gemini-api/docs/changelog)). If the
default (`gemini-2.5-flash`) stops working, set `GEMINI_MODEL` to whatever
Google currently recommends — no code change needed.

## API

| Method | Endpoint                    | Description                                   |
|--------|------------------------------|------------------------------------------------|
| POST   | `/api/job_descriptions`      | Create a JD: `{title, text}`                   |
| GET    | `/api/job_descriptions`      | List JDs                                        |
| POST   | `/api/resumes`               | Upload a resume (`multipart/form-data`, field `file`); runs extraction immediately |
| GET    | `/api/resumes`               | List resumes with extracted fields             |
| POST   | `/api/match`                 | `{resume_id, jd_id}` → runs scoring, stores + returns result |
| GET    | `/api/shortlist/<jd_id>`     | Ranked list of scored candidates for a JD       |

## Setup

Two interchangeable servers are included — same routes, same behavior,
same `db.py` / `parser.py` / `llm_matcher.py` underneath. Pick one.

### Option A — Flask (`app.py`)

```bash
cd resume-screener
python3 -m venv venv && source venv/bin/activate   # Git Bash on Windows: source venv/Scripts/activate
pip install -r requirements.txt

# optional but recommended — enables real LLM extraction/scoring
# get a key at https://aistudio.google.com/apikey
export GOOGLE_API_KEY=AIza...

python3 app.py
# → http://localhost:5000
```

### Option B — FastAPI + uvicorn (`app_fastapi.py`)

```bash
cd resume-screener
python3 -m venv venv && source venv/bin/activate   # Git Bash on Windows: source venv/Scripts/activate
pip install -r requirements-fastapi.txt

export GOOGLE_API_KEY=AIza...

uvicorn app_fastapi:app --reload --port 5000
# → http://localhost:5000
# interactive API docs → http://localhost:5000/docs
```

`--reload` restarts the server automatically on code changes — handy while
developing, drop it for anything resembling production.

The database (`screener.db`, SQLite) and its schema are created
automatically on first run.

## Try it with the sample data

`sample_data/sample_jd.txt` and `sample_data/sample_resume.txt` are included
for a quick smoke test:

1. Open `http://localhost:5000`.
2. File a job description — paste in the contents of `sample_jd.txt`.
3. Upload `sample_resume.txt` as a resume.
4. Run the match, then check the shortlist for the scored result.

## Project structure

```
resume-screener/
├── app.py                  # Flask routes (Option A)
├── app_fastapi.py           # FastAPI routes, run with uvicorn (Option B)
├── db.py                     # SQLite schema + queries (shared)
├── parser.py                  # PDF/text extraction (shared)
├── llm_matcher.py               # LLM prompts + heuristic fallback (shared)
├── requirements.txt              # deps for app.py
├── requirements-fastapi.txt       # deps for app_fastapi.py
├── .env.example
├── templates/index.html
├── static/{style.css, app.js}
└── sample_data/{sample_jd.txt, sample_resume.txt}
```

## Recording the demo video

Not included here (this repo produces code, not video), but a 2–3 min demo
should cover: filing a JD → uploading a resume → showing the extracted
fields → running a match → the shortlist with score + justification →
briefly opening `llm_matcher.py` to show the prompts.

## Notes / possible extensions

- Batch upload (multiple resumes matched against one JD in one action).
- Auth, if this were multi-recruiter.
- Swap SQLite for Postgres for concurrent/production use.
- Cache extraction results by resume hash to avoid re-running the LLM on
  re-uploads.
