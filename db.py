"""
db.py — SQLite storage layer for the Smart Resume Screener.

Tables:
  job_descriptions(id, title, raw_text, created_at)
  resumes(id, filename, raw_text, extracted_json, created_at)
  matches(id, resume_id, jd_id, score, justification, matched_skills_json,
          missing_skills_json, created_at)
"""

import sqlite3
import json
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screener.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS job_descriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    extracted_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resume_id INTEGER NOT NULL,
    jd_id INTEGER NOT NULL,
    score REAL NOT NULL,
    justification TEXT,
    matched_skills_json TEXT,
    missing_skills_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (resume_id) REFERENCES resumes(id),
    FOREIGN KEY (jd_id) REFERENCES job_descriptions(id)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_job_description(title, raw_text):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO job_descriptions (title, raw_text) VALUES (?, ?)",
            (title, raw_text),
        )
        return cur.lastrowid


def insert_resume(filename, raw_text, extracted=None):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO resumes (filename, raw_text, extracted_json) VALUES (?, ?, ?)",
            (filename, raw_text, json.dumps(extracted) if extracted else None),
        )
        return cur.lastrowid


def update_resume_extraction(resume_id, extracted):
    with get_conn() as conn:
        conn.execute(
            "UPDATE resumes SET extracted_json = ? WHERE id = ?",
            (json.dumps(extracted), resume_id),
        )


def insert_match(resume_id, jd_id, score, justification, matched_skills, missing_skills):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO matches
               (resume_id, jd_id, score, justification, matched_skills_json, missing_skills_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                resume_id,
                jd_id,
                score,
                justification,
                json.dumps(matched_skills),
                json.dumps(missing_skills),
            ),
        )
        return cur.lastrowid


def get_job_description(jd_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
        return dict(row) if row else None


def list_job_descriptions():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM job_descriptions ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def get_resume(resume_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()
        return dict(row) if row else None


def list_resumes():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM resumes ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def shortlist_for_jd(jd_id):
    """Return resumes matched against a JD, ordered by score descending."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id as match_id, m.score, m.justification,
                   m.matched_skills_json, m.missing_skills_json,
                   r.id as resume_id, r.filename, r.extracted_json
            FROM matches m
            JOIN resumes r ON r.id = m.resume_id
            WHERE m.jd_id = ?
            ORDER BY m.score DESC
            """,
            (jd_id,),
        ).fetchall()
        return [dict(r) for r in rows]
