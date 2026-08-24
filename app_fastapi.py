"""
app_fastapi.py — Smart Resume Screener backend (FastAPI + uvicorn).

Same API surface and behavior as app.py (Flask) — this reuses db.py,
parser.py, and llm_matcher.py unchanged. Pick whichever server you prefer;
they are interchangeable, not both required.

Run with:
    uvicorn app_fastapi:app --reload --port 5000
"""

import os
import json
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

import db
import parser
import llm_matcher

app = FastAPI(title="Smart Resume Screener")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

db.init_db()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB, matches the Flask version's cap


class JobDescriptionIn(BaseModel):
    title: str
    text: str


class MatchIn(BaseModel):
    resume_id: int
    jd_id: int


def _safe_json(raw: Optional[str]):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# Job descriptions
# ---------------------------------------------------------------------------

@app.post("/api/job_descriptions", status_code=201)
def create_job_description(payload: JobDescriptionIn):
    title = payload.title.strip()
    text = payload.text.strip()
    if not title or not text:
        raise HTTPException(status_code=400, detail="title and text are required")
    jd_id = db.insert_job_description(title, text)
    return {"id": jd_id, "title": title}


@app.get("/api/job_descriptions")
def get_job_descriptions():
    return db.list_job_descriptions()


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

@app.post("/api/resumes", status_code=201)
async def upload_resume(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="empty filename")

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (10MB limit)")

    try:
        text = parser.extract_text(raw_bytes, file.filename)
        text = parser.clean_text(text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"failed to parse file: {e}")

    if not text.strip():
        raise HTTPException(status_code=400, detail="no extractable text found in file")

    resume_id = db.insert_resume(file.filename, text)

    extracted = llm_matcher.extract_resume_fields(text)
    db.update_resume_extraction(resume_id, extracted)

    return {"id": resume_id, "filename": file.filename, "extracted": extracted}


@app.get("/api/resumes")
def get_resumes():
    resumes = db.list_resumes()
    for r in resumes:
        r["extracted"] = _safe_json(r.pop("extracted_json"))
    return resumes


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

@app.post("/api/match", status_code=201)
def match_resume_to_jd(payload: MatchIn):
    resume = db.get_resume(payload.resume_id)
    jd = db.get_job_description(payload.jd_id)
    if not resume:
        raise HTTPException(status_code=404, detail=f"resume {payload.resume_id} not found")
    if not jd:
        raise HTTPException(status_code=404, detail=f"job description {payload.jd_id} not found")

    result = llm_matcher.score_match(resume["raw_text"], jd["raw_text"])
    match_id = db.insert_match(
        resume_id=payload.resume_id,
        jd_id=payload.jd_id,
        score=result.get("score", 0),
        justification=result.get("justification", ""),
        matched_skills=result.get("matched_skills", []),
        missing_skills=result.get("missing_skills", []),
    )
    result["match_id"] = match_id
    return result


@app.get("/api/shortlist/{jd_id}")
def shortlist(jd_id: int):
    rows = db.shortlist_for_jd(jd_id)
    for r in rows:
        r["matched_skills"] = _safe_json(r.pop("matched_skills_json"))
        r["missing_skills"] = _safe_json(r.pop("missing_skills_json"))
        r["extracted"] = _safe_json(r.pop("extracted_json"))
    return rows


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run("app_fastapi:app", host="0.0.0.0", port=port, reload=True)
