"""
app.py — Smart Resume Screener backend (Flask).

Endpoints:
  POST /api/job_descriptions        Create a JD (title, text)
  GET  /api/job_descriptions        List JDs
  POST /api/resumes                 Upload a resume (multipart file: pdf/txt)
  GET  /api/resumes                 List resumes
  POST /api/match                   Trigger LLM extraction + scoring for a resume vs a JD
  GET  /api/shortlist/<jd_id>       Ranked shortlist for a JD
  GET  /                            Dashboard UI
"""

import os
from flask import Flask, request, jsonify, render_template

import db
import parser
import llm_matcher

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB upload cap

db.init_db()


@app.route("/")
def dashboard():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Job descriptions
# ---------------------------------------------------------------------------

@app.route("/api/job_descriptions", methods=["POST"])
def create_job_description():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    text = (data.get("text") or "").strip()
    if not title or not text:
        return jsonify({"error": "title and text are required"}), 400
    jd_id = db.insert_job_description(title, text)
    return jsonify({"id": jd_id, "title": title}), 201


@app.route("/api/job_descriptions", methods=["GET"])
def get_job_descriptions():
    return jsonify(db.list_job_descriptions())


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

@app.route("/api/resumes", methods=["POST"])
def upload_resume():
    if "file" not in request.files:
        return jsonify({"error": "no file part named 'file'"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "empty filename"}), 400

    raw_bytes = f.read()
    try:
        text = parser.extract_text(raw_bytes, f.filename)
        text = parser.clean_text(text)
    except Exception as e:
        return jsonify({"error": f"failed to parse file: {e}"}), 400

    if not text.strip():
        return jsonify({"error": "no extractable text found in file"}), 400

    resume_id = db.insert_resume(f.filename, text)

    # Extract structured fields via LLM (or heuristic fallback) immediately
    extracted = llm_matcher.extract_resume_fields(text)
    db.update_resume_extraction(resume_id, extracted)

    return jsonify({"id": resume_id, "filename": f.filename, "extracted": extracted}), 201


@app.route("/api/resumes", methods=["GET"])
def get_resumes():
    resumes = db.list_resumes()
    for r in resumes:
        r["extracted"] = _safe_json(r.pop("extracted_json"))
    return jsonify(resumes)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

@app.route("/api/match", methods=["POST"])
def match_resume_to_jd():
    data = request.get_json(silent=True) or {}
    resume_id = data.get("resume_id")
    jd_id = data.get("jd_id")
    if not resume_id or not jd_id:
        return jsonify({"error": "resume_id and jd_id are required"}), 400

    resume = db.get_resume(resume_id)
    jd = db.get_job_description(jd_id)
    if not resume:
        return jsonify({"error": f"resume {resume_id} not found"}), 404
    if not jd:
        return jsonify({"error": f"job description {jd_id} not found"}), 404

    result = llm_matcher.score_match(resume["raw_text"], jd["raw_text"])
    match_id = db.insert_match(
        resume_id=resume_id,
        jd_id=jd_id,
        score=result.get("score", 0),
        justification=result.get("justification", ""),
        matched_skills=result.get("matched_skills", []),
        missing_skills=result.get("missing_skills", []),
    )
    result["match_id"] = match_id
    return jsonify(result), 201


@app.route("/api/shortlist/<int:jd_id>", methods=["GET"])
def shortlist(jd_id):
    rows = db.shortlist_for_jd(jd_id)
    for r in rows:
        r["matched_skills"] = _safe_json(r.pop("matched_skills_json"))
        r["missing_skills"] = _safe_json(r.pop("missing_skills_json"))
        r["extracted"] = _safe_json(r.pop("extracted_json"))
    return jsonify(rows)


def _safe_json(raw):
    import json
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
