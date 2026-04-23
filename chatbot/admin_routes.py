"""
GovLearn Admin Dashboard routes.
Adds to the existing FastAPI app:
  GET  /admin           → login page
  POST /admin/login     → set session cookie
  GET  /admin/logout    → clear session
  GET  /admin/dashboard → dashboard UI
  POST /api/generate    → trigger full pipeline (SSE stream)
"""

import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Cookie, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "govlearn2024")
CHATBOT_DIR = Path(__file__).parent
SESSION_TOKEN = "gl_admin_ok"

router = APIRouter()


def is_authed(session: str | None) -> bool:
    return session == SESSION_TOKEN


# ── Login page ───────────────────────────────────────────────────────────────

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GovLearn Admin</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#0d1b2a;--paper:#f5f1eb;--gold:#c9a84c;--gold-lt:#e8d5a3;
  --muted:#7a7060;--err:#c0392b;--surface:#fff;--r:4px;
}
body{font-family:'DM Sans',sans-serif;background:var(--paper);min-height:100vh;
  display:flex;align-items:center;justify-content:center;
  background-image:radial-gradient(circle at 20% 80%,rgba(201,168,76,.08) 0%,transparent 60%),
                   radial-gradient(circle at 80% 20%,rgba(13,27,42,.04) 0%,transparent 50%)}
.wrap{width:100%;max-width:420px;padding:24px}
.card{background:var(--surface);border:1px solid rgba(0,0,0,.09);border-radius:8px;
  padding:48px 40px;box-shadow:0 4px 24px rgba(0,0,0,.07)}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:36px}
.logo-mark{width:36px;height:36px;background:var(--ink);border-radius:6px;
  display:flex;align-items:center;justify-content:center}
.logo-mark svg{width:20px;height:20px;fill:none;stroke:var(--gold);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.logo-name{font-family:'DM Serif Display',serif;font-size:22px;color:var(--ink);letter-spacing:-.3px}
.logo-tag{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;margin-left:auto;padding-top:2px}
h1{font-family:'DM Serif Display',serif;font-size:26px;color:var(--ink);margin-bottom:6px}
.sub{font-size:14px;color:var(--muted);margin-bottom:32px}
label{display:block;font-size:12px;font-weight:600;color:var(--ink);
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px}
input[type=password]{width:100%;padding:11px 14px;font-size:15px;font-family:inherit;
  border:1.5px solid #ddd;border-radius:var(--r);outline:none;
  transition:border-color .15s;background:var(--paper)}
input[type=password]:focus{border-color:var(--gold)}
.btn{width:100%;margin-top:20px;padding:13px;background:var(--ink);color:#fff;
  font-family:inherit;font-size:15px;font-weight:500;border:none;border-radius:var(--r);
  cursor:pointer;letter-spacing:.02em;transition:background .15s}
.btn:hover{background:#1a2f45}
.err{background:#fdf0ef;border:1px solid #f5c6c3;color:var(--err);
  padding:10px 14px;border-radius:var(--r);font-size:13px;margin-bottom:16px}
.divider{height:1px;background:linear-gradient(90deg,transparent,#e0d8cc,transparent);margin:28px 0}
.footer{text-align:center;font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<div class="wrap"><div class="card">
  <div class="logo">
    <div class="logo-mark">
      <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
    </div>
    <span class="logo-name">GovLearn</span>
    <span class="logo-tag">Admin</span>
  </div>
  <h1>Welcome back</h1>
  <p class="sub">Sign in to access the course management dashboard.</p>
  {error}
  <form method="post" action="/admin/login">
    <label for="pw">Password</label>
    <input type="password" id="pw" name="password" placeholder="Enter admin password" autofocus>
    <button class="btn" type="submit">Sign in &rarr;</button>
  </form>
  <div class="divider"></div>
  <p class="footer">GovLearn &middot; Parliamentary Learning Management System</p>
</div></div>
</body>
</html>"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GovLearn &middot; Course Generator</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --ink:#0d1b2a;--paper:#f5f1eb;--gold:#c9a84c;--gold-lt:#f0e6c8;
  --muted:#7a7060;--surface:#fff;--border:#e5dfd5;
  --success:#1a7f4b;--err:#c0392b;--r:6px;
}
body{font-family:'DM Sans',sans-serif;background:var(--paper);color:var(--ink);min-height:100vh;
  background-image:radial-gradient(ellipse at 10% 90%,rgba(201,168,76,.07) 0%,transparent 55%),
                   radial-gradient(ellipse at 90% 10%,rgba(13,27,42,.04) 0%,transparent 50%)}

.hdr{background:var(--ink);color:#fff;padding:0 32px;height:56px;
  display:flex;align-items:center;justify-content:space-between;
  box-shadow:0 2px 12px rgba(0,0,0,.25)}
.hdr-brand{display:flex;align-items:center;gap:12px}
.hdr-mark{width:30px;height:30px;background:var(--gold);border-radius:5px;
  display:flex;align-items:center;justify-content:center}
.hdr-mark svg{width:16px;height:16px;fill:none;stroke:var(--ink);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.hdr-name{font-family:'DM Serif Display',serif;font-size:19px;letter-spacing:-.2px}
.hdr-badge{font-size:10px;background:rgba(255,255,255,.12);padding:3px 8px;
  border-radius:20px;letter-spacing:.1em;text-transform:uppercase}
.hdr-logout{font-size:13px;color:rgba(255,255,255,.55);text-decoration:none;transition:color .15s}
.hdr-logout:hover{color:#fff}

.page{max-width:960px;margin:0 auto;padding:40px 24px 80px}
.page-title{font-family:'DM Serif Display',serif;font-size:34px;color:var(--ink);
  margin-bottom:6px;letter-spacing:-.5px}
.page-sub{font-size:15px;color:var(--muted);margin-bottom:36px}

.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:36px;box-shadow:0 2px 16px rgba(0,0,0,.05);margin-bottom:24px}
.card-title{font-size:12px;font-weight:600;text-transform:uppercase;
  letter-spacing:.12em;color:var(--gold);margin-bottom:22px}

.drop-zone{border:2px dashed var(--border);border-radius:var(--r);
  padding:48px 24px;text-align:center;cursor:pointer;
  transition:border-color .2s,background .2s;position:relative;overflow:hidden}
.drop-zone:hover,.drop-zone.drag{border-color:var(--gold);background:var(--gold-lt)}
.drop-zone input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;height:100%}
.drop-icon{font-size:38px;margin-bottom:12px;opacity:.35}
.drop-main{font-size:16px;font-weight:500;margin-bottom:4px}
.drop-sub{font-size:13px;color:var(--muted)}
.drop-file{font-size:14px;color:var(--success);font-weight:600;margin-top:10px;display:none}

.field-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:22px}
@media(max-width:600px){.field-row{grid-template-columns:1fr}}
label{display:block;font-size:12px;font-weight:600;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);margin-bottom:6px}
input[type=text]{width:100%;padding:10px 14px;font-size:15px;font-family:inherit;
  border:1.5px solid var(--border);border-radius:var(--r);outline:none;
  background:var(--paper);transition:border-color .15s,background .15s}
input[type=text]:focus{border-color:var(--gold);background:#fff}

.btn-generate{display:flex;align-items:center;justify-content:center;gap:10px;
  width:100%;margin-top:24px;padding:14px;background:var(--ink);color:#fff;
  font-family:inherit;font-size:16px;font-weight:500;border:none;border-radius:var(--r);
  cursor:pointer;transition:background .15s,opacity .15s;letter-spacing:.01em}
.btn-generate:hover:not(:disabled){background:#1a2f45}
.btn-generate:disabled{opacity:.4;cursor:not-allowed}
@keyframes spin{to{transform:rotate(360deg)}}
.spin-icon{display:none;animation:spin .7s linear infinite}
.btn-generate.loading .spin-icon{display:inline-block}
.btn-generate.loading .idle-txt{display:none}

.progress-panel{display:none}
.progress-panel.show{display:block}
.prog-steps{display:flex;flex-direction:column}
.step{display:flex;align-items:flex-start;gap:16px;padding:16px 0;
  border-bottom:1px solid var(--border)}
.step:last-child{border-bottom:none}
.step-icon{width:32px;height:32px;border-radius:50%;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:13px;font-weight:700;margin-top:1px;
  background:var(--paper);border:2px solid var(--border);color:var(--muted);
  transition:all .25s}
.step-icon.running{border-color:var(--gold);color:var(--gold)}
.step-icon.running::after{content:'';display:block;width:8px;height:8px;
  background:var(--gold);border-radius:50%;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.8)}}
.step-icon.done{border-color:var(--success);background:var(--success);color:#fff}
.step-icon.done::after{content:'✓'}
.step-icon.err{border-color:var(--err);background:var(--err);color:#fff}
.step-icon.err::after{content:'✗'}
.step-icon.wait{color:var(--muted)}
.step-body{flex:1;padding-top:5px}
.step-label{font-size:15px;font-weight:500}
.step-detail{font-size:13px;color:var(--muted);margin-top:3px;min-height:16px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:600px}

.log-wrap{margin-top:18px}
.log-toggle{font-size:12px;color:var(--muted);cursor:pointer;user-select:none;
  display:inline-flex;align-items:center;gap:6px}
.log-box{background:#0d1b2a;border-radius:var(--r);padding:16px;margin-top:8px;
  font-family:'Courier New',monospace;font-size:12px;line-height:1.7;
  color:#8fafc8;max-height:180px;overflow-y:auto;display:none}
.log-box.show{display:block}
.log-ok{color:#6ee7b7}.log-warn{color:#fcd34d}.log-err{color:#fca5a5}

.result-card{display:none;background:linear-gradient(140deg,#0d1b2a 0%,#162a40 100%);
  color:#fff;border-radius:10px;padding:40px;margin-top:8px}
.result-card.show{display:block;animation:fadeUp .4s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
.result-eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--gold);margin-bottom:10px;font-weight:600}
.result-title{font-family:'DM Serif Display',serif;font-size:26px;margin-bottom:6px;
  letter-spacing:-.3px}
.result-sub{font-size:14px;opacity:.6;margin-bottom:28px}
.result-stats{display:flex;gap:32px;margin-bottom:32px;flex-wrap:wrap}
.rstat-v{font-size:30px;font-weight:800;color:var(--gold);display:block;line-height:1}
.rstat-l{font-size:11px;opacity:.5;text-transform:uppercase;letter-spacing:.08em;margin-top:4px;display:block}
.result-actions{display:flex;gap:12px;flex-wrap:wrap}
.btn-action{display:inline-flex;align-items:center;gap:8px;padding:12px 24px;
  border-radius:var(--r);font-size:14px;font-weight:600;cursor:pointer;
  text-decoration:none;transition:all .15s;font-family:inherit;border:none;letter-spacing:.01em}
.btn-moodle{background:var(--gold);color:var(--ink)}
.btn-moodle:hover{background:#d9b55c}
.btn-reset{background:rgba(255,255,255,.08);color:rgba(255,255,255,.8);
  border:1px solid rgba(255,255,255,.15)}
.btn-reset:hover{background:rgba(255,255,255,.15);color:#fff}
</style>
</head>
<body>

<header class="hdr">
  <div class="hdr-brand">
    <div class="hdr-mark">
      <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
    </div>
    <span class="hdr-name">GovLearn</span>
    <span class="hdr-badge">Course Generator</span>
  </div>
  <a class="hdr-logout" href="/admin/logout">Sign out</a>
</header>

<div class="page">
  <h1 class="page-title">Policy &rarr; Course</h1>
  <p class="page-sub">Upload a policy document and GovLearn will generate a complete interactive SCORM course &mdash; automatically.</p>

  <div class="card" id="uploadCard">
    <div class="card-title">New Course</div>

    <div class="drop-zone" id="dropZone">
      <input type="file" id="pdfInput" accept=".pdf">
      <div class="drop-icon">&#128196;</div>
      <div class="drop-main">Drop your policy PDF here</div>
      <div class="drop-sub">or click to browse &mdash; PDF only</div>
      <div class="drop-file" id="dropFile"></div>
    </div>

    <div class="field-row">
      <div>
        <label for="courseId">Module ID</label>
        <input type="text" id="courseId" placeholder="e.g. cyber-101" value="cyber-101">
      </div>
      <div>
        <label for="courseName">Course Name <span style="font-weight:400;text-transform:none;letter-spacing:0">(optional)</span></label>
        <input type="text" id="courseName" placeholder="Auto-detected from document">
      </div>
    </div>

    <button class="btn-generate" id="btnGenerate" disabled>
      <span class="idle-txt">&#10022; Generate Course</span>
      <span class="spin-icon">&#8635;</span>
      <span class="loading-label" style="display:none">Generating&hellip;</span>
    </button>
  </div>

  <div class="card progress-panel" id="progressPanel">
    <div class="card-title">Pipeline Progress</div>
    <div class="prog-steps">
      <div class="step">
        <div class="step-icon wait" id="s1i">1</div>
        <div class="step-body">
          <div class="step-label">Extract content from PDF</div>
          <div class="step-detail" id="s1d">Waiting&hellip;</div>
        </div>
      </div>
      <div class="step">
        <div class="step-icon wait" id="s2i">2</div>
        <div class="step-body">
          <div class="step-label">Structure into learning modules with AI</div>
          <div class="step-detail" id="s2d">Waiting&hellip;</div>
        </div>
      </div>
      <div class="step">
        <div class="step-icon wait" id="s3i">3</div>
        <div class="step-body">
          <div class="step-label">Build interactive SCORM course</div>
          <div class="step-detail" id="s3d">Waiting&hellip;</div>
        </div>
      </div>
      <div class="step">
        <div class="step-icon wait" id="s4i">4</div>
        <div class="step-body">
          <div class="step-label">Publish to Moodle LMS</div>
          <div class="step-detail" id="s4d">Waiting&hellip;</div>
        </div>
      </div>
      <div class="step">
        <div class="step-icon wait" id="s5i">5</div>
        <div class="step-body">
          <div class="step-label">Load into AI knowledge base</div>
          <div class="step-detail" id="s5d">Waiting&hellip;</div>
        </div>
      </div>
    </div>
    <div class="log-wrap">
      <span class="log-toggle" id="logToggle">&#9658; Show detailed log</span>
      <div class="log-box" id="logBox"></div>
    </div>
  </div>

  <div class="result-card" id="resultCard">
    <div class="result-eyebrow">Course Ready</div>
    <div class="result-title" id="resultTitle">Untitled Course</div>
    <div class="result-sub">Published and ready for learners in Moodle.</div>
    <div class="result-stats" id="resultStats"></div>
    <div class="result-actions">
      <a class="btn-action btn-moodle" id="moodleLink" href="#" target="_blank">Open in Moodle &rarr;</a>
      <button class="btn-action btn-reset" onclick="location.reload()">Generate another</button>
    </div>
  </div>
</div>

<script>
var selectedFile = null;
var currentStep  = 0;

// ── Drop zone ──────────────────────────────────────────────────────────────
var dz = document.getElementById('dropZone');
var fi = document.getElementById('pdfInput');

dz.addEventListener('dragover',  function(e){ e.preventDefault(); dz.classList.add('drag'); });
dz.addEventListener('dragleave', function(){  dz.classList.remove('drag'); });
dz.addEventListener('drop',      function(e){
  e.preventDefault(); dz.classList.remove('drag');
  var f = e.dataTransfer.files[0];
  if (f && f.type === 'application/pdf') setFile(f);
  else alert('Please drop a PDF file.');
});
fi.addEventListener('change', function(){ if (fi.files[0]) setFile(fi.files[0]); });

function setFile(f) {
  selectedFile = f;
  var el = document.getElementById('dropFile');
  el.textContent = '\u2713 ' + f.name + '  (' + Math.round(f.size/1024) + ' KB)';
  el.style.display = 'block';
  dz.querySelector('.drop-main').textContent = 'PDF selected';
  dz.querySelector('.drop-sub').textContent  = 'Click to change file';
  document.getElementById('btnGenerate').disabled = false;
}

// ── Generate ───────────────────────────────────────────────────────────────
document.getElementById('btnGenerate').addEventListener('click', function() {
  if (!selectedFile) return;
  var btn = document.getElementById('btnGenerate');
  btn.classList.add('loading');
  btn.disabled = true;
  btn.querySelector('.loading-label').style.display = 'inline';

  document.getElementById('uploadCard').style.opacity = '.55';
  document.getElementById('uploadCard').style.pointerEvents = 'none';
  document.getElementById('progressPanel').classList.add('show');
  setStep(1, 'running', 'Reading PDF\u2026');

  var fd = new FormData();
  fd.append('pdf',         selectedFile);
  fd.append('module_id',   document.getElementById('courseId').value  || 'cyber-101');
  fd.append('course_name', document.getElementById('courseName').value || '');

  fetch('/api/generate', { method: 'POST', body: fd })
    .then(function(r) {
      if (!r.ok) throw new Error('Server returned ' + r.status);
      var reader  = r.body.getReader();
      var decoder = new TextDecoder();
      var buf     = '';
      function pump() {
        return reader.read().then(function(d) {
          if (d.done) return;
          buf += decoder.decode(d.value, { stream: true });
          var lines = buf.split('\n');
          buf = lines.pop();
          lines.forEach(function(line) {
            if (line.startsWith('data: ')) {
              try { handle(JSON.parse(line.slice(6))); } catch(e) {}
            }
          });
          return pump();
        });
      }
      return pump();
    })
    .catch(function(e) {
      log('ERROR: ' + e.message, 'err');
      setStep(currentStep || 1, 'err', e.message);
    });
});

function setStep(n, state, detail) {
  currentStep = n;
  var icon = document.getElementById('s' + n + 'i');
  icon.className = 'step-icon ' + state;
  if (state === 'wait') icon.textContent = n;
  else                  icon.textContent = '';
  if (detail) document.getElementById('s' + n + 'd').textContent = detail;
}

function log(msg, cls) {
  var box  = document.getElementById('logBox');
  var line = document.createElement('div');
  line.className = 'log-' + (cls || 'ok');
  line.textContent = msg;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

document.getElementById('logToggle').addEventListener('click', function() {
  var box = document.getElementById('logBox');
  box.classList.toggle('show');
  this.innerHTML = box.classList.contains('show')
    ? '&#9660; Hide detailed log'
    : '&#9658; Show detailed log';
});

function handle(ev) {
  if (ev.msg) log(ev.msg, ev.ok === false ? 'err' : ev.warn ? 'warn' : 'ok');

  if (ev.step) {
    // mark previous step done
    if (currentStep && currentStep < ev.step) {
      setStep(currentStep, 'done', document.getElementById('s' + currentStep + 'd').textContent);
    }
    setStep(ev.step, 'running', ev.msg || '');
  }
  if (ev.detail) {
    document.getElementById('s' + currentStep + 'd').textContent = ev.detail;
  }
  if (ev.error) {
    setStep(currentStep, 'err', ev.error);
    log('FAILED: ' + ev.error, 'err');
  }
  if (ev.done) {
    for (var i = 1; i <= 5; i++) {
      var ic = document.getElementById('s' + i + 'i');
      if (!ic.classList.contains('err') && !ic.classList.contains('done')) {
        setStep(i, 'done', 'Complete');
      }
    }
    showResult(ev);
    document.getElementById('btnGenerate').classList.remove('loading');
  }
}

function showResult(ev) {
  var rc = document.getElementById('resultCard');
  rc.classList.add('show');
  if (ev.course_title) document.getElementById('resultTitle').textContent = ev.course_title;
  var stats = '';
  if (ev.slides)    stats += '<div><span class="rstat-v">' + ev.slides    + '</span><span class="rstat-l">Modules</span></div>';
  if (ev.questions) stats += '<div><span class="rstat-v">' + ev.questions + '</span><span class="rstat-l">Quiz Questions</span></div>';
  stats += '<div><span class="rstat-v">SCORM 1.2</span><span class="rstat-l">Standard</span></div>';
  document.getElementById('resultStats').innerHTML = stats;
  if (ev.moodle_url) document.getElementById('moodleLink').href = ev.moodle_url;
  rc.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
</script>
</body>
</html>"""


# ── Route handlers ────────────────────────────────────────────────────────────

@router.get("/admin", response_class=HTMLResponse)
def admin_login_page(gl_session: str | None = Cookie(default=None)):
    if is_authed(gl_session):
        return RedirectResponse("/admin/dashboard", status_code=302)
    return HTMLResponse(LOGIN_HTML.replace("{error}", ""))


@router.post("/admin/login")
def admin_login(password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        resp = RedirectResponse("/admin/dashboard", status_code=302)
        resp.set_cookie("gl_session", SESSION_TOKEN, httponly=True, samesite="lax")
        return resp
    html = LOGIN_HTML.replace(
        "{error}",
        '<div class="err">Incorrect password. Please try again.</div>'
    )
    return HTMLResponse(html, status_code=401)


@router.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin", status_code=302)
    resp.delete_cookie("gl_session")
    return resp


@router.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(gl_session: str | None = Cookie(default=None)):
    if not is_authed(gl_session):
        return RedirectResponse("/admin", status_code=302)
    return HTMLResponse(DASHBOARD_HTML)


@router.post("/api/generate")
async def generate_course(
    pdf: UploadFile = File(...),
    module_id: str = Form("cyber-101"),
    course_name: str = Form(""),
    gl_session: str | None = Cookie(default=None),
):
    if not is_authed(gl_session):
        raise HTTPException(status_code=401, detail="Not authenticated")

    tmp_dir  = tempfile.mkdtemp(prefix="govlearn_")
    pdf_path = os.path.join(tmp_dir, "policy.pdf")
    kb_path  = str(CHATBOT_DIR / "knowledge_base.json")
    zip_path = os.path.join(tmp_dir, f"{module_id}.zip")

    with open(pdf_path, "wb") as f:
        f.write(await pdf.read())

    async def stream():
        try:
            def ev(step=None, msg="", detail=None, **kw):
                d = {"msg": msg}
                if step is not None: d["step"]   = step
                if detail is not None: d["detail"] = detail
                d.update(kw)
                return f"data: {json.dumps(d)}\n\n"

            # ── Step 1: generate_content.py ───────────────────────────────
            yield ev(step=1, msg="Extracting content from PDF…")
            gen_script = str(CHATBOT_DIR / "generate_content.py")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, gen_script,
                "--pdf", pdf_path, "--module-id", module_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(CHATBOT_DIR),
            )
            async for raw in proc.stdout:
                txt = raw.decode().rstrip()
                if txt:
                    yield ev(msg=txt, detail=txt[:90])
            await proc.wait()
            if proc.returncode != 0:
                yield ev(msg="Content generation failed", ok=False, error="generate_content.py exited with error")
                return

            # Count chunks
            n_slides = n_questions = 0
            if os.path.exists(kb_path):
                with open(kb_path) as f:
                    chunks = json.load(f)
                n_slides = sum(1 for c in chunks if "quiz" not in c.get("metadata", {}).get("section_id", "").lower())

            # ── Step 2 label ──────────────────────────────────────────────
            yield ev(step=2, msg=f"AI structured {n_slides} learning modules")
            await asyncio.sleep(0.3)

            # ── Step 3: generate_scorm.py ─────────────────────────────────
            yield ev(step=3, msg="Building interactive SCORM course…")
            scorm_script = str(CHATBOT_DIR / "generate_scorm.py")
            proc2 = await asyncio.create_subprocess_exec(
                sys.executable, scorm_script,
                "--kb", kb_path, "--module-id", module_id, "--output", zip_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(CHATBOT_DIR),
            )
            async for raw in proc2.stdout:
                txt = raw.decode().rstrip()
                if txt:
                    yield ev(msg=txt)
            await proc2.wait()
            if proc2.returncode != 0:
                yield ev(msg="SCORM generation failed", ok=False, error="generate_scorm.py exited with error")
                return

            # Count quiz questions from the zip
            if os.path.exists(zip_path):
                with zipfile.ZipFile(zip_path) as zf:
                    if "index.html" in zf.namelist():
                        idx = zf.read("index.html").decode(errors="replace")
                        m = re.search(r'var QUESTIONS\s*=\s*(\[.*?\]);', idx, re.DOTALL)
                        if m:
                            try: n_questions = len(json.loads(m.group(1)))
                            except Exception: pass

            # ── Step 4: upload to Moodle ──────────────────────────────────
            yield ev(step=4, msg="Uploading SCORM package to Moodle…")
            moodle_url_env = os.environ.get("MOODLE_URL", "http://192.168.122.153:8080")
            moodle_token   = os.environ.get("MOODLE_TOKEN", "d687610cf5075667f4b0c79dea1957c0")
            upload = await _upload_scorm(zip_path, module_id, moodle_url_env, moodle_token, kb_path)
            if not upload["ok"]:
                yield ev(msg=upload.get("error", "Upload failed"), ok=False, error=upload.get("error"))
                return
            course_id    = upload["course_id"]
            course_title = upload.get("course_title", module_id)
            moodle_course_url = f"{moodle_url_env}/course/view.php?id={course_id}"
            yield ev(msg=f"Course live at {moodle_course_url}", detail="Published to Moodle")

            # ── Step 5: pgvector ingestion ────────────────────────────────
            yield ev(step=5, msg="Loading content into AI knowledge base…")
            chatbot_url = os.environ.get("CHATBOT_URL", "http://localhost:8000")
            ingested = await _ingest_chunks(kb_path, chatbot_url)
            yield ev(msg=f"Ingested {ingested} chunks into pgvector")

            # ── Done ──────────────────────────────────────────────────────
            yield f"data: {json.dumps({'done': True, 'course_title': course_title, 'slides': n_slides, 'questions': n_questions, 'moodle_url': moodle_course_url, 'msg': 'All done!'})}\n\n"

        except Exception as ex:
            yield f"data: {json.dumps({'error': str(ex), 'ok': False, 'msg': str(ex)})}\n\n"
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(stream(), media_type="text/event-stream")


async def _upload_scorm(zip_path, module_id, moodle_url, token, kb_path):
    """Upload SCORM zip to Moodle, create course, add activity. Returns dict."""
    import aiohttp

    api = f"{moodle_url}/webservice/rest/server.php"

    def params(fn, **kw):
        return {"wstoken": token, "wsfunction": fn, "moodlewsrestformat": "json", **kw}

    try:
        async with aiohttp.ClientSession() as sess:
            # Delete existing course with same shortname
            async with sess.post(api, data=params("core_course_get_courses_by_field", field="shortname", value=module_id)) as r:
                existing = await r.json()
            if existing.get("courses"):
                eid = existing["courses"][0]["id"]
                await sess.post(api, data=params("core_course_delete_courses", **{"courseids[0]": eid}))

            # Derive title from knowledge base
            course_title = f"GovLearn: {module_id.upper()}"
            if os.path.exists(kb_path):
                with open(kb_path) as f:
                    chunks = json.load(f)
                if chunks:
                    first = chunks[0].get("section", "")
                    if first:
                        course_title = f"GovLearn: {module_id.upper()} — {first}"

            # Create course
            async with sess.post(api, data=params(
                "core_course_create_courses",
                **{
                    "courses[0][fullname]":       course_title,
                    "courses[0][shortname]":      module_id,
                    "courses[0][categoryid]":     1,
                    "courses[0][summary]":        "Auto-generated by GovLearn from policy document.",
                    "courses[0][summaryformat]":  1,
                    "courses[0][format]":         "topics",
                    "courses[0][numsections]":    2,
                    "courses[0][visible]":        1,
                }
            )) as r:
                result = await r.json()
            if isinstance(result, dict) and "exception" in result:
                return {"ok": False, "error": result.get("message", "Course creation failed")}
            course_id = result[0]["id"]

            # Upload zip file
            with open(zip_path, "rb") as zf:
                form = aiohttp.FormData()
                form.add_field("token",    token)
                form.add_field("filearea", "draft")
                form.add_field("itemid",   "0")
                form.add_field("filepath", "/")
                form.add_field("filename", f"{module_id}.zip")
                form.add_field("file", zf, filename=f"{module_id}.zip", content_type="application/zip")
                async with sess.post(f"{moodle_url}/webservice/upload.php", data=form) as r:
                    text = await r.text()
                    try:
                        up = json.loads(text)
                    except Exception:
                        return {"ok": False, "error": f"Upload response not JSON: {text[:200]}"}

            if not up or isinstance(up, dict) and "error" in up:
                return {"ok": False, "error": f"File upload failed: {up}"}

            item_id  = up[0]["itemid"]
            filename = up[0]["filename"]

            # Add SCORM activity
            async with sess.post(api, data=params(
                "mod_scorm_add_scorm",
                **{
                    "coursemodule[course]":      course_id,
                    "coursemodule[section]":     1,
                    "name":                      course_title,
                    "intro":                     "<p>Interactive course generated by GovLearn.</p>",
                    "introformat":               1,
                    "packagefilepath":           f"/{filename}",
                    "packagefileitemid":         item_id,
                    "scormtype":                 0,
                    "version":                   "",
                    "maxgrade":                  100,
                    "grademethod":               0,
                    "maxattempt":                0,
                    "whatgrade":                 0,
                    "forcecompleted":            0,
                    "forcenewattempt":           0,
                    "lastattemptlock":           0,
                    "displayattemptstatus":      1,
                    "displaycoursestructure":    0,
                    "updatefreq":                0,
                    "sha1hash":                  "",
                    "md5hash":                   "",
                    "revision":                  0,
                    "launch":                    0,
                    "skipview":                  1,
                    "hidebrowse":                0,
                    "hidetoc":                   0,
                    "nav":                       1,
                    "navpositionleft":           -100,
                    "navpositiontop":            -100,
                    "auto":                      0,
                    "popup":                     0,
                    "options":                   "",
                    "width":                     100,
                    "height":                    500,
                    "timeopen":                  0,
                    "timeclose":                 0,
                    "timemodified":              0,
                    "completionstatusrequired":  4,
                    "completionscorerequired":   0,
                    "completionstatusallscos":   0,
                    "visible":                   1,
                }
            )) as r:
                scorm_r = await r.json()

            if isinstance(scorm_r, dict) and "exception" in scorm_r:
                # Course was created but SCORM activity failed — still return ok with warning
                return {"ok": True, "course_id": course_id, "course_title": course_title,
                        "warn": scorm_r.get("message", "SCORM activity not added")}

            return {"ok": True, "course_id": course_id, "course_title": course_title}

    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _ingest_chunks(kb_path, chatbot_url):
    import aiohttp
    if not os.path.exists(kb_path):
        return 0
    with open(kb_path) as f:
        chunks = json.load(f)
    ok = 0
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as sess:
        for chunk in chunks:
            try:
                async with sess.post(f"{chatbot_url}/ingest", json=chunk) as r:
                    if r.status == 200:
                        ok += 1
            except Exception:
                pass
    return ok
