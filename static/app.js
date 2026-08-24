const $ = (sel) => document.querySelector(sel);

let jds = [];
let resumes = [];

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `Request failed (${res.status})`);
  }
  return res.json();
}

// ---------------- Job descriptions ----------------

async function loadJDs() {
  jds = await api("/api/job_descriptions");
  const chipRow = $("#jd-list");
  chipRow.innerHTML = jds.length
    ? jds.map((j) => `<span class="chip">#${j.id} ${escapeHtml(j.title)}</span>`).join("")
    : "";

  const fillSelect = (select) => {
    select.innerHTML = jds
      .map((j) => `<option value="${j.id}">#${j.id} — ${escapeHtml(j.title)}</option>`)
      .join("");
  };
  fillSelect($("#match-jd"));
  fillSelect($("#shortlist-jd"));

  if (jds.length) loadShortlist($("#shortlist-jd").value);
}

$("#jd-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const title = $("#jd-title").value.trim();
  const text = $("#jd-text").value.trim();
  await api("/api/job_descriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, text }),
  });
  e.target.reset();
  await loadJDs();
});

// ---------------- Resumes ----------------

async function loadResumes() {
  resumes = await api("/api/resumes");
  const chipRow = $("#resume-list");
  chipRow.innerHTML = resumes.length
    ? resumes.map((r) => `<span class="chip">#${r.id} ${escapeHtml(r.filename)}</span>`).join("")
    : "";

  $("#match-resume").innerHTML = resumes
    .map((r) => `<option value="${r.id}">#${r.id} — ${escapeHtml(r.filename)}</option>`)
    .join("");
}

$("#resume-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fileInput = $("#resume-file");
  if (!fileInput.files.length) return;
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  btn.textContent = "Extracting…";
  try {
    await api("/api/resumes", { method: "POST", body: fd });
    e.target.reset();
    await loadResumes();
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload & extract";
  }
});

// ---------------- Matching ----------------

$("#match-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const jd_id = Number($("#match-jd").value);
  const resume_id = Number($("#match-resume").value);
  const btn = e.target.querySelector("button");
  btn.disabled = true;
  btn.textContent = "Scoring…";
  try {
    await api("/api/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jd_id, resume_id }),
    });
    $("#shortlist-jd").value = String(jd_id);
    await loadShortlist(jd_id);
  } finally {
    btn.disabled = false;
    btn.textContent = "Score this candidate";
  }
});

// ---------------- Shortlist ----------------

$("#shortlist-jd").addEventListener("change", (e) => loadShortlist(e.target.value));

async function loadShortlist(jdId) {
  const container = $("#shortlist");
  if (!jdId) {
    container.innerHTML = `<div class="empty-state">File a job description to begin.</div>`;
    return;
  }
  const rows = await api(`/api/shortlist/${jdId}`);
  if (!rows.length) {
    container.innerHTML = `<div class="empty-state">No candidates scored against this role yet.</div>`;
    return;
  }
  container.innerHTML = rows.map(renderCandidate).join("");
}

function renderCandidate(row) {
  const scoreClass = row.score >= 7 ? "score-high" : row.score >= 4 ? "score-mid" : "score-low";
  const matched = (row.matched_skills || [])
    .map((s) => `<span class="skill-tag matched">${escapeHtml(s)}</span>`).join("");
  const missing = (row.missing_skills || [])
    .map((s) => `<span class="skill-tag missing">${escapeHtml(s)}</span>`).join("");
  const name = row.extracted?.name;

  return `
    <div class="candidate">
      <div class="candidate-body">
        <h3>${escapeHtml(name || row.filename)}</h3>
        <div class="filename">${escapeHtml(row.filename)}</div>
        <p class="justification">${escapeHtml(row.justification || "")}</p>
        ${matched ? `<div class="skill-block"><div class="label">Matched</div><div class="skill-tags">${matched}</div></div>` : ""}
        ${missing ? `<div class="skill-block"><div class="label">Gaps</div><div class="skill-tags">${missing}</div></div>` : ""}
      </div>
      <div class="stamp ${scoreClass}">
        <div class="score-num">${row.score}</div>
        <div class="score-den">/ 10</div>
        <div class="stamp-label">REVIEWED</div>
      </div>
    </div>
  `;
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ---------------- Init ----------------

(async function init() {
  await loadJDs();
  await loadResumes();
})();
