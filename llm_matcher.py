"""
llm_matcher.py — LLM-powered resume field extraction and JD match scoring.

Uses the Google Gemini API (generateContent) directly over HTTPS (no SDK
dependency). Requires GOOGLE_API_KEY (or GEMINI_API_KEY) to be set in the
environment — get one at https://aistudio.google.com/apikey. If neither is
set, falls back to a lightweight heuristic (keyword-overlap) implementation
so the app remains demoable without an API key — this fallback is clearly
labeled in the output and should NOT be presented as the LLM result.

Model note: Gemini model IDs are periodically retired (see
https://ai.google.dev/gemini-api/docs/changelog). The default below
(GEMINI_MODEL env var, falling back to "gemini-2.5-flash") is overridable
without touching code if Google deprecates it — set:
    export GEMINI_MODEL=gemini-3-flash   # or whatever is current
"""

import os
import re
import json
import requests

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def _call_gemini(system: str, user_prompt: str, max_tokens: int = 1024) -> str:
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) not set")

    url = f"{GEMINI_API_BASE}/{MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
        },
    }
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {data}")
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model response, tolerating stray text/fences."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    return json.loads(match.group(0))


# ---------------------------------------------------------------------------
# Structured extraction: resume text -> {skills, experience, education}
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a resume parsing engine. Given raw resume \
text, extract structured data ONLY. Respond with a single JSON object and \
nothing else — no preamble, no markdown fences. Schema:

{
  "name": string | null,
  "skills": [string, ...],
  "experience": [
    {"title": string, "company": string | null, "duration": string | null, "summary": string}
  ],
  "education": [
    {"degree": string, "institution": string | null, "year": string | null}
  ],
  "total_years_experience": number | null
}

If a field cannot be determined, use null or an empty list. Be concise in summaries \
(one sentence each)."""


def extract_resume_fields(resume_text: str) -> dict:
    try:
        raw = _call_gemini(EXTRACTION_SYSTEM_PROMPT, resume_text[:12000])
        return {**_extract_json(raw), "_source": "llm"}
    except Exception:
        return {**_heuristic_extract(resume_text), "_source": "heuristic_fallback"}


def _heuristic_extract(text: str) -> dict:
    """Very rough fallback used only when no API key is configured."""
    common_skills = [
        "python", "java", "javascript", "typescript", "node.js", "react", "sql",
        "aws", "docker", "kubernetes", "machine learning", "nlp", "fastapi",
        "flask", "django", "c++", "go", "git", "rest api", "llm", "pandas",
    ]
    lower = text.lower()
    found_skills = sorted({s for s in common_skills if s in lower})
    years_match = re.search(r"(\d+)\+?\s+years?", lower)
    return {
        "name": None,
        "skills": found_skills,
        "experience": [],
        "education": [],
        "total_years_experience": int(years_match.group(1)) if years_match else None,
    }


# ---------------------------------------------------------------------------
# Match scoring: resume + JD -> {score, justification, matched/missing skills}
# ---------------------------------------------------------------------------

SCORING_SYSTEM_PROMPT = """You are an expert technical recruiter. Compare a \
candidate's resume with a job description and rate the fit on a scale of 1-10. \
Respond with a single JSON object ONLY — no preamble, no markdown fences. Schema:

{
  "score": number,            // 1-10, can be a float like 7.5
  "justification": string,    // 2-4 sentences explaining the score
  "matched_skills": [string, ...],
  "missing_skills": [string, ...]
}

Be specific and evidence-based: cite concrete resume details (roles, projects, \
skills) that justify the score rather than generic statements."""


def score_match(resume_text: str, jd_text: str) -> dict:
    user_prompt = (
        f"Compare the following resume with this job description and rate fit "
        f"on 1-10 with justification.\n\n"
        f"--- JOB DESCRIPTION ---\n{jd_text[:6000]}\n\n"
        f"--- RESUME ---\n{resume_text[:8000]}"
    )
    try:
        raw = _call_gemini(SCORING_SYSTEM_PROMPT, user_prompt)
        result = _extract_json(raw)
        result["_source"] = "llm"
        return result
    except Exception as e:
        return {**_heuristic_score(resume_text, jd_text), "_source": "heuristic_fallback",
                "_error": str(e)}


def _heuristic_score(resume_text: str, jd_text: str) -> dict:
    """Fallback keyword-overlap scorer used only when no API key is configured."""
    resume_words = set(re.findall(r"[a-zA-Z+#.]+", resume_text.lower()))
    jd_words = set(re.findall(r"[a-zA-Z+#.]+", jd_text.lower()))
    jd_keywords = {w for w in jd_words if len(w) > 3}
    overlap = resume_words & jd_keywords
    missing = list(jd_keywords - resume_words)[:10]
    ratio = len(overlap) / max(len(jd_keywords), 1)
    score = round(1 + ratio * 9, 1)
    return {
        "score": score,
        "justification": (
            f"Heuristic keyword overlap: {len(overlap)} shared terms with the "
            f"job description out of {len(jd_keywords)} candidate keywords. "
            f"(No ANTHROPIC_API_KEY configured — set one for real LLM-based scoring.)"
        ),
        "matched_skills": sorted(overlap)[:15],
        "missing_skills": missing,
    }
