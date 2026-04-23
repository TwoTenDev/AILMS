#!/usr/bin/env python3
"""
GovLearn SCORM 1.2 package generator.

Reads knowledge_base.json and outputs a standards-compliant SCORM 1.2 zip
package with rich HTML5 content ready to upload to any LMS.

Usage:
  python generate_scorm.py --kb knowledge_base.json --module-id cyber-101
Output:
  cyber-101.zip
"""

import argparse
import json
import os
import re
import sys
import zipfile
from html import escape
from urllib import request as urlrequest

# ─── SCORM 1.2 API Wrapper ─────────────────────────────────────────────────
# pipwerks-compatible implementation (MIT).  The generator attempts to fetch
# the canonical upstream file first; this string is the fallback.
SCORM_API_JS_FALLBACK = """\
/* GovLearn SCORM 1.2 API Wrapper — pipwerks-compatible (MIT) */
var pipwerks = pipwerks || {};
pipwerks.SCORM = {
    version: "1.2",
    connection: { isActive: false },
    _api: null,

    _find: function (win) {
        var depth = 0;
        while (depth < 10) {
            if (typeof win.API !== "undefined" && win.API !== null) return win.API;
            if (!win.parent || win.parent === win) break;
            win = win.parent;
            depth++;
        }
        if (typeof win.opener !== "undefined" && win.opener) {
            return pipwerks.SCORM._find(win.opener);
        }
        return null;
    },

    _getAPI: function () {
        if (!this._api) this._api = this._find(window);
        return this._api;
    },

    init: function () {
        var api = this._getAPI();
        if (!api) { console.warn("[SCORM] API not found — running standalone"); return false; }
        var r = api.LMSInitialize("");
        this.connection.isActive = (r === true || r === "true");
        if (this.connection.isActive) console.log("[SCORM] Initialized");
        return this.connection.isActive;
    },

    get: function (key) {
        var api = this._getAPI();
        if (!api || !this.connection.isActive) return "";
        return api.LMSGetValue(key);
    },

    set: function (key, val) {
        var api = this._getAPI();
        if (!api || !this.connection.isActive) return false;
        var r = api.LMSSetValue(key, String(val));
        return (r === true || r === "true");
    },

    commit: function () {
        var api = this._getAPI();
        if (!api || !this.connection.isActive) return false;
        return (api.LMSCommit("") === "true");
    },

    quit: function () {
        var api = this._getAPI();
        if (!api || !this.connection.isActive) return false;
        api.LMSCommit("");
        var r = api.LMSFinish("");
        this.connection.isActive = false;
        return (r === "true");
    }
};
"""

PIPWERKS_URL = (
    "https://raw.githubusercontent.com/pipwerks/scorm-api-wrapper"
    "/master/src/JavaScript/SCORM_API_wrapper.js"
)


def fetch_scorm_api_js() -> str:
    try:
        with urlrequest.urlopen(PIPWERKS_URL, timeout=8) as resp:
            content = resp.read().decode("utf-8")
            print("  ✓ Downloaded pipwerks SCORM API wrapper")
            return content
    except Exception as e:
        print(f"  ⚠ Could not download pipwerks wrapper ({e}), using built-in fallback")
        return SCORM_API_JS_FALLBACK


# ─── Markdown → HTML ────────────────────────────────────────────────────────

def _inline(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def md_to_html(text: str) -> str:
    lines = text.split("\n")
    out = []
    in_ul = False

    for raw in lines:
        line = raw.rstrip()

        def close_list():
            nonlocal in_ul
            if in_ul:
                out.append("</ul>")
                in_ul = False

        if line.startswith("### "):
            close_list(); out.append(f"<h3>{_inline(escape(line[4:].strip()))}</h3>")
        elif line.startswith("## "):
            close_list(); out.append(f"<h2>{_inline(escape(line[3:].strip()))}</h2>")
        elif line.startswith("# "):
            close_list(); out.append(f"<h2>{_inline(escape(line[2:].strip()))}</h2>")
        elif line.startswith("- ") or line.startswith("* "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline(escape(line[2:].strip()))}</li>")
        elif line.strip() in ("---", "***", "___"):
            close_list(); out.append("<hr/>")
        elif line.startswith("> "):
            close_list()
            out.append(f'<blockquote>{_inline(escape(line[2:].strip()))}</blockquote>')
        elif line.strip() == "":
            close_list()
        else:
            close_list()
            out.append(f"<p>{_inline(escape(line.strip()))}</p>")

    if in_ul:
        out.append("</ul>")
    return "\n".join(out)


# ─── Quiz parser (reuse logic from create_moodle_course.py) ─────────────────

def parse_quiz(content: str) -> list[dict]:
    questions = []
    blocks = re.split(r"\n(?=Q\d*:)", content.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        q_m = re.search(r"Q\d*:\s*(.+?)(?=\nA\))", block, re.DOTALL)
        if not q_m:
            continue
        question_text = q_m.group(1).strip()
        options = {}
        for letter in ["A", "B", "C", "D"]:
            m = re.search(
                rf"{letter}\)\s*(.+?)(?=\n[B-D]\)|\nCorrect:|\Z)", block, re.DOTALL
            )
            if m:
                options[letter] = m.group(1).strip()
        correct_m = re.search(r"Correct:\s*([A-D])", block)
        correct = correct_m.group(1) if correct_m else "A"
        exp_m = re.search(r"Explanation:\s*(.+)", block, re.DOTALL)
        explanation = exp_m.group(1).strip() if exp_m else ""
        if question_text and len(options) >= 2:
            questions.append(
                {
                    "text": question_text,
                    "options": options,
                    "correct": correct,
                    "explanation": explanation,
                }
            )
    return questions


# ─── CSS ────────────────────────────────────────────────────────────────────

COURSE_CSS = """\
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --navy:        #1e3a5f;
  --navy-lt:     #2a5298;
  --accent:      #1d4ed8;
  --accent-lt:   #3b82f6;
  --success:     #16a34a;
  --error:       #dc2626;
  --bg:          #f1f5f9;
  --surface:     #ffffff;
  --text:        #1e293b;
  --text-muted:  #64748b;
  --border:      #e2e8f0;
  --sh:          0 1px 3px rgba(0,0,0,.10), 0 1px 2px rgba(0,0,0,.06);
  --sh-md:       0 4px 6px -1px rgba(0,0,0,.10), 0 2px 4px -1px rgba(0,0,0,.06);
  --r:           8px;
  --font:        -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  font-size: 16px;
  line-height: 1.65;
}

/* ── Header ── */
.c-header {
  background: var(--navy);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  height: 58px;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(0,0,0,.35);
  z-index: 10;
}
.h-brand { display: flex; align-items: center; gap: 12px; }
.h-logo {
  width: 30px; height: 30px;
  background: var(--accent);
  border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
}
.h-label {
  font-size: 11px; font-weight: 700; opacity: .65;
  letter-spacing: .1em; text-transform: uppercase;
}
.h-title {
  font-size: 15px; font-weight: 600;
  max-width: 480px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.h-prog { font-size: 13px; opacity: .75; }

/* ── Progress track ── */
.c-track { height: 4px; background: #334155; flex-shrink: 0; }
.c-fill  { height: 100%; background: var(--accent-lt); transition: width .4s ease; }

/* ── Body ── */
.c-body {
  flex: 1; overflow-y: auto;
  padding: 40px 24px;
  display: flex; justify-content: center;
}
.slide-wrap { max-width: 860px; width: 100%; }
.fade-up { animation: fadeUp .3s ease forwards; }
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── Slide typography ── */
.slide-tag {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; font-weight: 700; color: var(--accent-lt);
  text-transform: uppercase; letter-spacing: .1em; margin-bottom: 10px;
}
.slide-h1 {
  font-size: 26px; font-weight: 700; color: var(--navy);
  line-height: 1.25; margin-bottom: 24px;
}

/* ── Content card ── */
.card {
  background: var(--surface); border-radius: var(--r);
  box-shadow: var(--sh); padding: 32px; margin-bottom: 18px;
}
.card h2 { font-size: 19px; color: var(--navy); margin: 22px 0 10px; }
.card h2:first-child { margin-top: 0; }
.card h3 { font-size: 16px; color: var(--navy-lt); margin: 18px 0 8px; }
.card p  { margin-bottom: 12px; }
.card p:last-child { margin-bottom: 0; }
.card ul, .card ol { margin: 8px 0 12px 22px; }
.card li { margin-bottom: 5px; }
.card strong { color: var(--navy); }
.card hr { border: none; border-top: 1px solid var(--border); margin: 16px 0; }
.card code {
  background: #f1f5f9; padding: 2px 6px;
  border-radius: 4px; font-family: 'Courier New', monospace; font-size: .88em;
}
.card blockquote {
  border-left: 4px solid var(--accent-lt); padding: 12px 16px;
  margin: 14px 0; background: #eff6ff; border-radius: 0 4px 4px 0;
  color: var(--navy); font-style: italic;
}

/* callout variants */
.callout {
  display: flex; gap: 14px; padding: 16px;
  border-radius: var(--r); margin-bottom: 16px; border: 1px solid;
}
.callout-i { background: #eff6ff; border-color: #bfdbfe; }
.callout-w { background: #fffbeb; border-color: #fde68a; }
.callout-k { background: #f0fdf4; border-color: #bbf7d0; }
.callout-icon { font-size: 17px; flex-shrink: 0; margin-top: 2px; }
.callout-i .callout-icon { color: var(--accent); }
.callout-w .callout-icon { color: #b45309; }
.callout-k .callout-icon { color: var(--success); }
.callout-body { flex: 1; font-size: 15px; line-height: 1.55; }

/* ── Welcome screen ── */
.welcome {
  display: flex; flex-direction: column; align-items: center;
  text-align: center; padding: 56px 32px;
}
.welcome-icon {
  width: 76px; height: 76px; background: var(--navy); border-radius: 14px;
  display: flex; align-items: center; justify-content: center;
  font-size: 32px; color: #fff; margin-bottom: 26px;
}
.welcome h1 { font-size: 30px; font-weight: 700; color: var(--navy); margin-bottom: 14px; }
.welcome-sub {
  font-size: 17px; color: var(--text-muted);
  max-width: 520px; margin-bottom: 36px; line-height: 1.6;
}
.welcome-stats { display: flex; gap: 40px; margin-bottom: 40px; }
.stat { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.stat-v { font-size: 26px; font-weight: 800; color: var(--navy); }
.stat-l { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .08em; }

/* ── Quiz ── */
.quiz-hdr { text-align: center; margin-bottom: 28px; }
.quiz-hdr h2 { font-size: 22px; color: var(--navy); margin-bottom: 6px; }
.quiz-hdr p  { color: var(--text-muted); font-size: 15px; }
.q-card { background: var(--surface); border-radius: var(--r); box-shadow: var(--sh-md); padding: 34px; margin-bottom: 18px; }
.q-num  { font-size: 11px; font-weight: 700; color: var(--accent-lt); text-transform: uppercase; letter-spacing: .1em; margin-bottom: 10px; }
.q-text { font-size: 18px; font-weight: 600; color: var(--navy); line-height: 1.4; margin-bottom: 22px; }
.opts   { display: grid; gap: 9px; }
.opt {
  display: flex; align-items: center; gap: 14px; width: 100%;
  padding: 13px 18px; background: var(--bg);
  border: 2px solid var(--border); border-radius: var(--r);
  font-size: 15px; color: var(--text); cursor: pointer;
  text-align: left; transition: border-color .15s, background .15s;
  font-family: var(--font);
}
.opt:hover:not(:disabled) { border-color: var(--accent-lt); background: #eff6ff; }
.opt.correct  { border-color: var(--success); background: #f0fdf4; color: #166534; }
.opt.wrong    { border-color: var(--error);   background: #fef2f2; color: #991b1b; }
.opt:disabled { cursor: default; }
.opt-ltr {
  width: 28px; height: 28px; border-radius: 50%;
  border: 2px solid currentColor; background: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 12px; flex-shrink: 0;
}
.feedback {
  display: none; margin-top: 14px; padding: 13px 16px;
  border-radius: var(--r); font-size: 15px;
  animation: fadeUp .2s ease;
}
.feedback.correct  { background: #f0fdf4; border: 1px solid #86efac; color: #15803d; display: block; }
.feedback.wrong    { background: #fef2f2; border: 1px solid #fca5a5; color: #991b1b; display: block; }
.q-nav { display: flex; justify-content: flex-end; margin-top: 16px; }

/* ── Score screen ── */
.score-screen { text-align: center; padding: 48px 32px; }
.score-ring {
  width: 136px; height: 136px; border-radius: 50%;
  margin: 0 auto 26px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-size: 34px; font-weight: 800;
}
.score-ring.pass { background: #f0fdf4; border: 5px solid var(--success); color: var(--success); }
.score-ring.fail { background: #fef2f2; border: 5px solid var(--error);   color: var(--error); }
.score-lbl { font-size: 12px; font-weight: 500; }
.score-msg { font-size: 22px; font-weight: 600; color: var(--navy); margin-bottom: 10px; }
.score-sub { color: var(--text-muted); margin-bottom: 28px; }
.score-retry { margin-top: 8px; }

/* ── Footer nav ── */
.c-footer {
  background: var(--surface); border-top: 1px solid var(--border);
  padding: 14px 24px; display: flex; align-items: center;
  justify-content: space-between; flex-shrink: 0;
  box-shadow: 0 -2px 6px rgba(0,0,0,.04);
}
.btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 10px 22px; border-radius: 6px;
  font-size: 15px; font-weight: 500; cursor: pointer;
  border: none; transition: background .15s, opacity .15s;
  font-family: var(--font); line-height: 1;
}
.btn:disabled { opacity: .4; cursor: not-allowed; }
.btn-primary   { background: var(--accent);    color: #fff; }
.btn-primary:hover:not(:disabled)   { background: var(--accent-lt); }
.btn-secondary { background: transparent; color: var(--text-muted); border: 1px solid var(--border); }
.btn-secondary:hover:not(:disabled) { background: var(--bg); }
.btn-success   { background: var(--success); color: #fff; }
.btn-success:hover:not(:disabled)   { background: #15803d; }
.nav-mid { font-size: 13px; color: var(--text-muted); }

/* ── Responsive ── */
@media (max-width: 600px) {
  .h-title, .h-label { display: none; }
  .c-header { padding: 0 14px; }
  .c-body   { padding: 20px 14px; }
  .card { padding: 20px; }
  .slide-h1 { font-size: 20px; }
  .q-card   { padding: 22px; }
  .c-footer { padding: 10px 14px; }
  .btn      { padding: 8px 16px; font-size: 14px; }
  .welcome-stats { gap: 24px; }
}
"""


# ─── imsmanifest.xml ────────────────────────────────────────────────────────

def build_manifest(module_id: str, title: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", module_id)
    esc_title = escape(title)
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="com.govlearn.{safe_id}" version="1"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd
                      http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="org_{safe_id}">
    <organization identifier="org_{safe_id}">
      <title>{esc_title}</title>
      <item identifier="item_main" identifierref="res_main" isvisible="true">
        <title>{esc_title}</title>
        <adlcp:masteryscore>80</adlcp:masteryscore>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res_main" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
      <file href="js/scorm_api.js"/>
    </resource>
  </resources>
</manifest>
"""


# ─── Individual slide HTML (standalone reference pages) ─────────────────────

def build_slide_html(slide: dict, index: int, total: int, course_title: str) -> str:
    content_html = md_to_html(slide["content"])
    section = escape(slide.get("section", ""))
    title = escape(slide.get("title", section))
    course_title_esc = escape(course_title)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {course_title_esc}</title>
  <link rel="stylesheet" href="../css/course.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css"
        crossorigin="anonymous">
</head>
<body>
<header class="c-header">
  <div class="h-brand">
    <div class="h-logo"><i class="fas fa-graduation-cap"></i></div>
    <span class="h-label">GovLearn</span>
    <span class="h-title">{course_title_esc}</span>
  </div>
  <span class="h-prog">Page {index} of {total}</span>
</header>
<div class="c-track"><div class="c-fill" style="width:{round(index/total*100)}%"></div></div>
<main class="c-body">
  <div class="slide-wrap fade-up">
    <div class="slide-tag"><i class="fas fa-book-open"></i> {section}</div>
    <h1 class="slide-h1">{title}</h1>
    <div class="card">{content_html}</div>
  </div>
</main>
<footer class="c-footer">
  <a href="{'slide_' + str(index-1).zfill(3) + '.html' if index > 1 else '#'}"
     class="btn btn-secondary" {'style="visibility:hidden"' if index <= 1 else ''}>
    <i class="fas fa-chevron-left"></i> Previous
  </a>
  <span class="nav-mid">Page {index} of {total}</span>
  <a href="{'slide_' + str(index+1).zfill(3) + '.html' if index < total else '../quiz/quiz.html'}"
     class="btn btn-primary">
    {'Next' if index < total else 'Take Quiz'} <i class="fas fa-chevron-right"></i>
  </a>
</footer>
</body>
</html>
"""


# ─── Quiz standalone HTML ────────────────────────────────────────────────────

def build_quiz_html(questions: list[dict], course_title: str) -> str:
    q_json = json.dumps(questions, ensure_ascii=False)
    course_title_esc = escape(course_title)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Knowledge Check — {course_title_esc}</title>
  <link rel="stylesheet" href="../css/course.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css"
        crossorigin="anonymous">
</head>
<body>
<header class="c-header">
  <div class="h-brand">
    <div class="h-logo"><i class="fas fa-graduation-cap"></i></div>
    <span class="h-label">GovLearn</span>
    <span class="h-title">{course_title_esc}</span>
  </div>
  <span class="h-prog">Knowledge Check</span>
</header>
<div class="c-track"><div class="c-fill" style="width:100%"></div></div>
<main class="c-body" id="quizMain"></main>
<footer class="c-footer">
  <span></span>
  <span class="nav-mid" id="qProg"></span>
  <button class="btn btn-primary" id="btnQNext" disabled>
    Next <i class="fas fa-chevron-right"></i>
  </button>
</footer>
<script>
var QUESTIONS = {q_json};
var qi = 0, score = 0, answered = false;

function render() {{
  if (qi >= QUESTIONS.length) {{ showScore(); return; }}
  var q = QUESTIONS[qi];
  answered = false;
  document.getElementById("btnQNext").disabled = true;
  document.getElementById("qProg").textContent =
    "Question " + (qi+1) + " of " + QUESTIONS.length;

  var opts = "";
  var letters = Object.keys(q.options);
  letters.forEach(function(l) {{
    opts += '<button class="opt" onclick="answer(this,\\'' + l + '\\',\\'' + q.correct + '\\',\\'' +
            q.explanation.replace(/'/g,"\\\\x27").replace(/"/g,"&quot;") + '\\')">' +
            '<span class="opt-ltr">' + l + '</span>' +
            '<span>' + escHtml(q.options[l]) + '</span></button>';
  }});

  document.getElementById("quizMain").innerHTML =
    '<div class="slide-wrap fade-up">' +
    '<div class="quiz-hdr"><h2>Knowledge Check</h2>' +
    '<p>Select the best answer for each question.</p></div>' +
    '<div class="q-card">' +
    '<div class="q-num">Question ' + (qi+1) + ' of ' + QUESTIONS.length + '</div>' +
    '<div class="q-text">' + escHtml(q.text) + '</div>' +
    '<div class="opts">' + opts + '</div>' +
    '<div class="feedback" id="fb"></div>' +
    '</div></div>';
}}

function escHtml(s) {{
  return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}

function answer(btn, chosen, correct, explanation) {{
  if (answered) return;
  answered = true;
  var allBtns = document.querySelectorAll(".opt");
  allBtns.forEach(function(b) {{ b.disabled = true; }});
  var fb = document.getElementById("fb");
  if (chosen === correct) {{
    btn.classList.add("correct");
    score++;
    fb.className = "feedback correct";
    fb.innerHTML = '<i class="fas fa-check-circle"></i> Correct! ' + escHtml(explanation);
  }} else {{
    btn.classList.add("wrong");
    allBtns.forEach(function(b) {{
      if (b.textContent.trim().startsWith(correct)) b.classList.add("correct");
    }});
    fb.className = "feedback wrong";
    fb.innerHTML = '<i class="fas fa-times-circle"></i> The correct answer is ' +
                   correct + '. ' + escHtml(explanation);
  }}
  document.getElementById("btnQNext").disabled = false;
}}

function showScore() {{
  var pct = QUESTIONS.length > 0 ? Math.round((score / QUESTIONS.length) * 100) : 0;
  var pass = pct >= 80;
  document.getElementById("qProg").textContent = "";
  document.getElementById("btnQNext").style.display = "none";
  document.getElementById("quizMain").innerHTML =
    '<div class="slide-wrap fade-up"><div class="score-screen">' +
    '<div class="score-ring ' + (pass?"pass":"fail") + '">' +
    pct + '%<span class="score-lbl">Score</span></div>' +
    '<div class="score-msg">' + (pass ? "Well done!" : "Keep practising") + '</div>' +
    '<div class="score-sub">You answered ' + score + ' of ' + QUESTIONS.length +
    ' questions correctly. Passing score is 80%.</div>' +
    (pass ? '' : '<button class="btn btn-secondary score-retry" onclick="restart()">Try again</button>') +
    '</div></div>';
}}

function restart() {{ qi = 0; score = 0; render(); document.getElementById("btnQNext").style.display = ""; }}

document.getElementById("btnQNext").addEventListener("click", function() {{
  qi++;
  render();
}});

render();
</script>
</body>
</html>
"""


# ─── Main index.html (SCO) ───────────────────────────────────────────────────

def build_index_html(
    slides: list[dict],
    questions: list[dict],
    course_title: str,
    module_id: str,
) -> str:
    slides_json = json.dumps(
        [{"section": s.get("section", ""), "title": s.get("title", s.get("section", "")),
          "content": s.get("content", "")} for s in slides],
        ensure_ascii=False,
    )
    questions_json = json.dumps(questions, ensure_ascii=False)
    course_title_esc = escape(course_title)
    n_slides = len(slides)
    n_q = len(questions)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{course_title_esc}</title>
  <link rel="stylesheet" href="css/course.css">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css"
        crossorigin="anonymous">
  <script src="js/scorm_api.js"></script>
</head>
<body>

<header class="c-header">
  <div class="h-brand">
    <div class="h-logo"><i class="fas fa-graduation-cap"></i></div>
    <span class="h-label">GovLearn</span>
    <span class="h-title" id="hTitle">{course_title_esc}</span>
  </div>
  <span class="h-prog" id="hProg"></span>
</header>
<div class="c-track"><div class="c-fill" id="progFill" style="width:0%"></div></div>
<main class="c-body" id="main"></main>
<footer class="c-footer">
  <button class="btn btn-secondary" id="btnPrev" disabled>
    <i class="fas fa-chevron-left"></i> Previous
  </button>
  <span class="nav-mid" id="navMid"></span>
  <button class="btn btn-primary" id="btnNext">
    Start <i class="fas fa-chevron-right"></i>
  </button>
</footer>

<script>
// ─── Course data ────────────────────────────────────────────────
var SLIDES    = {slides_json};
var QUESTIONS = {questions_json};
var TITLE     = {json.dumps(course_title)};
var MODULE_ID = {json.dumps(module_id)};

// ─── State ────────────────────────────────────────────────────────
// index 0 = welcome, 1..N = slides, N+1 = quiz, N+2 = score
var S = {{
  idx:          0,
  quizQ:        0,    // current question
  quizScore:    0,
  quizAnswered: false,
  quizDone:     false,
  scorm:        false
}};
var N      = SLIDES.length;
var QUIZ_I = N + 1;
var END_I  = N + 2;

// ─── SCORM ────────────────────────────────────────────────────────
function scormInit() {{
  S.scorm = pipwerks.SCORM.init();
  if (!S.scorm) return;
  var status = pipwerks.SCORM.get("cmi.core.lesson_status");
  if (!status || status === "not attempted") {{
    pipwerks.SCORM.set("cmi.core.lesson_status", "incomplete");
  }}
  var loc = parseInt(pipwerks.SCORM.get("cmi.core.lesson_location") || "0", 10);
  if (!isNaN(loc) && loc > 0 && loc <= END_I) S.idx = loc;
}}

function scormSave() {{
  if (!S.scorm) return;
  pipwerks.SCORM.set("cmi.core.lesson_location", String(S.idx));
  if (pipwerks.SCORM.save) pipwerks.SCORM.save(); else if (pipwerks.SCORM.commit) pipwerks.SCORM.commit();
}}

function scormReport(score) {{
  if (!S.scorm) return;
  var pct  = QUESTIONS.length > 0 ? Math.round((score / QUESTIONS.length) * 100) : 100;
  var pass = pct >= 80;
  pipwerks.SCORM.set("cmi.core.score.raw", String(pct));
  pipwerks.SCORM.set("cmi.core.score.min", "0");
  pipwerks.SCORM.set("cmi.core.score.max", "100");
  pipwerks.SCORM.set("cmi.core.lesson_status", pass ? "passed" : "failed");
  if (pipwerks.SCORM.save) pipwerks.SCORM.save(); else if (pipwerks.SCORM.commit) pipwerks.SCORM.commit();
}}

// ─── Helpers ──────────────────────────────────────────────────────
function esc(s) {{
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}}

function mdToHtml(text) {{
  var lines = text.split("\\n"), out = [], inList = false;
  lines.forEach(function(raw) {{
    var ln = raw.trimEnd();
    function closeList() {{ if (inList) {{ out.push("</ul>"); inList = false; }} }}
    function inline(s) {{
      s = s.replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>");
      s = s.replace(/\\*(.+?)\\*/g,   "<em>$1</em>");
      s = s.replace(/`(.+?)`/g,       "<code>$1</code>");
      return s;
    }}
    if      (ln.match(/^### /)) {{ closeList(); out.push("<h3>" + inline(esc(ln.slice(4).trim())) + "</h3>"); }}
    else if (ln.match(/^## /))  {{ closeList(); out.push("<h2>" + inline(esc(ln.slice(3).trim())) + "</h2>"); }}
    else if (ln.match(/^# /))   {{ closeList(); out.push("<h2>" + inline(esc(ln.slice(2).trim())) + "</h2>"); }}
    else if (ln.match(/^[-*] /))  {{
      if (!inList) {{ out.push("<ul>"); inList = true; }}
      out.push("<li>" + inline(esc(ln.slice(2).trim())) + "</li>");
    }}
    else if (ln.match(/^> /))  {{ closeList(); out.push("<blockquote>" + inline(esc(ln.slice(2))) + "</blockquote>"); }}
    else if (ln.trim() === "" || ln.trim().match(/^---+$/)) {{ closeList(); }}
    else {{ closeList(); out.push("<p>" + inline(esc(ln.trim())) + "</p>"); }}
  }});
  if (inList) out.push("</ul>");
  return out.join("\\n");
}}

// ─── Nav ──────────────────────────────────────────────────────────
function updateNav() {{
  var prev = document.getElementById("btnPrev");
  var next = document.getElementById("btnNext");
  var mid  = document.getElementById("navMid");
  var fill = document.getElementById("progFill");
  var prog = document.getElementById("hProg");

  prev.disabled = (S.idx === 0);
  next.disabled = false;

  if (S.idx === 0) {{
    next.innerHTML = 'Start <i class="fas fa-chevron-right"></i>';
    mid.textContent = "";
    prog.textContent = "Introduction";
    fill.style.width = "0%";
  }} else if (S.idx <= N) {{
    next.innerHTML = (S.idx < N ? 'Next' : 'Take Quiz') + ' <i class="fas fa-chevron-right"></i>';
    mid.textContent = "Page " + S.idx + " of " + N;
    prog.textContent = "Page " + S.idx + " of " + N;
    fill.style.width = Math.round((S.idx / (N + 2)) * 100) + "%";
  }} else if (S.idx === QUIZ_I) {{
    next.disabled = !S.quizAnswered;
    next.innerHTML = (S.quizQ >= QUESTIONS.length - 1 && S.quizAnswered) ? 'Finish <i class="fas fa-check"></i>' : 'Next <i class="fas fa-chevron-right"></i>';
    mid.textContent = "Question " + (Math.min(S.quizQ + 1, QUESTIONS.length)) + " of " + QUESTIONS.length;
    prog.textContent = "Knowledge Check";
    fill.style.width = Math.round(((N + 1) / (N + 2)) * 100) + "%";
  }} else {{
    next.innerHTML = 'Finish <i class="fas fa-check"></i>';
    next.className = "btn btn-success";
    mid.textContent = "Complete";
    prog.textContent = "Complete";
    fill.style.width = "100%";
  }}
}}

function go(delta) {{
  if (S.idx === QUIZ_I && delta === 1) {{
    // In quiz mode - advance question, not slide
    if (!S.quizAnswered) return;
    S.quizQ++;
    if (S.quizQ >= QUESTIONS.length) {{
      scormReport(S.quizScore);
      S.quizDone = true;
      S.idx = END_I;
    }}
    S.quizAnswered = false;
    render();
    scormSave();
    document.querySelector(".c-body").scrollTop = 0;
    return;
  }}
  S.idx = Math.max(0, Math.min(END_I, S.idx + delta));
  render();
  scormSave();
  document.querySelector(".c-body").scrollTop = 0;
}}

// ─── Screens ──────────────────────────────────────────────────────
function renderWelcome() {{
  var numQ = QUESTIONS.length > 0
    ? '<div class="stat"><span class="stat-v">' + QUESTIONS.length +
      '</span><span class="stat-l">Questions</span></div>' : "";
  document.getElementById("main").innerHTML =
    '<div class="slide-wrap fade-up"><div class="welcome">' +
    '<div class="welcome-icon"><i class="fas fa-graduation-cap"></i></div>' +
    '<h1>' + esc(TITLE) + '</h1>' +
    '<p class="welcome-sub">A GovLearn professional development module. ' +
    'Work through the content at your own pace, then complete the knowledge check.</p>' +
    '<div class="welcome-stats">' +
    '<div class="stat"><span class="stat-v">' + N + '</span><span class="stat-l">Sections</span></div>' +
    numQ +
    '<div class="stat"><span class="stat-v">~' + Math.max(5, Math.round((N * 2 + QUESTIONS.length) / 3)) +
    ' min</span><span class="stat-l">Duration</span></div>' +
    '</div>' +
    '<button class="btn btn-primary" style="font-size:17px;padding:14px 36px" onclick="go(1)">' +
    'Begin Course <i class="fas fa-arrow-right"></i></button>' +
    '</div></div>';
}}

function renderSlide(i) {{
  var s = SLIDES[i];
  var section = s.section || "";
  var title   = s.title   || section;
  document.getElementById("main").innerHTML =
    '<div class="slide-wrap fade-up">' +
    (section ? '<div class="slide-tag"><i class="fas fa-bookmark"></i> ' + esc(section) + '</div>' : '') +
    '<h1 class="slide-h1">' + esc(title) + '</h1>' +
    '<div class="card">' + mdToHtml(s.content) + '</div>' +
    '</div>';
}}

function renderQuiz() {{
  if (!QUESTIONS.length) {{
    S.idx = END_I;
    render();
    return;
  }}
  if (S.quizDone || S.idx === END_I) {{ renderScore(); return; }}
  var q = QUESTIONS[S.quizQ];
  S.quizAnswered = false;
  document.getElementById("btnNext").disabled = true;

  var opts = "";
  Object.keys(q.options).forEach(function(l) {{
    opts += '<button class="opt" onclick="quizAnswer(this,\\'' + l + '\\',' +
            'QUESTIONS[' + S.quizQ + '].correct,' +
            'QUESTIONS[' + S.quizQ + '].explanation)">' +
            '<span class="opt-ltr">' + l + '</span>' +
            '<span>' + esc(q.options[l]) + '</span></button>';
  }});

  document.getElementById("main").innerHTML =
    '<div class="slide-wrap fade-up">' +
    '<div class="quiz-hdr"><h2><i class="fas fa-clipboard-check"></i> Knowledge Check</h2>' +
    '<p>Select the best answer for each question.</p></div>' +
    '<div class="q-card">' +
    '<div class="q-num">Question ' + (S.quizQ + 1) + ' of ' + QUESTIONS.length + '</div>' +
    '<div class="q-text">' + esc(q.text) + '</div>' +
    '<div class="opts">' + opts + '</div>' +
    '<div class="feedback" id="qFeedback"></div>' +
    '</div></div>';

  document.getElementById("navMid").textContent =
    "Question " + (S.quizQ + 1) + " of " + QUESTIONS.length;
}}

function quizAnswer(btn, chosen, correct, explanation) {{
  if (S.quizAnswered) return;
  S.quizAnswered = true;
  var allBtns = document.querySelectorAll(".opt");
  allBtns.forEach(function(b) {{ b.disabled = true; }});
  var fb = document.getElementById("qFeedback");
  if (chosen === correct) {{
    btn.classList.add("correct");
    S.quizScore++;
    fb.className = "feedback correct";
    fb.innerHTML = '<i class="fas fa-check-circle"></i> Correct! ' + esc(explanation);
  }} else {{
    btn.classList.add("wrong");
    allBtns.forEach(function(b) {{
      if (b.querySelector(".opt-ltr").textContent.trim() === correct) b.classList.add("correct");
    }});
    fb.className = "feedback wrong";
    fb.innerHTML = '<i class="fas fa-times-circle"></i> The correct answer is ' +
                   correct + '. ' + esc(explanation);
  }}
  // Advance quiz on next click
  S.quizAnswered = true;
  document.getElementById("btnPrev").disabled = true;
  updateNav();
}}

function renderScore() {{
  var pct  = QUESTIONS.length > 0
    ? Math.round((S.quizScore / QUESTIONS.length) * 100)
    : 100;
  var pass = pct >= 80;
  document.getElementById("btnNext").disabled = false;
  document.getElementById("btnNext").className = "btn btn-success";
  document.getElementById("btnNext").innerHTML = 'Finish <i class="fas fa-check"></i>';
  document.getElementById("main").innerHTML =
    '<div class="slide-wrap fade-up"><div class="score-screen card">' +
    '<div class="score-ring ' + (pass ? "pass" : "fail") + '">' +
    pct + '%<br><span class="score-lbl">Score</span></div>' +
    '<div class="score-msg">' + (pass ? "Well done!" : "Keep practising") + '</div>' +
    '<div class="score-sub">' +
    (QUESTIONS.length > 0
      ? 'You answered ' + S.quizScore + ' of ' + QUESTIONS.length +
        ' questions correctly.'
      : 'Course complete.') +
    ' Passing score is 80%.' +
    '</div>' +
    (!pass && QUESTIONS.length > 0
      ? '<button class="btn btn-secondary" onclick="retryQuiz()" style="margin-top:14px">' +
        '<i class="fas fa-redo"></i> Retry Quiz</button>'
      : '') +
    '</div></div>';
}}

function retryQuiz() {{
  S.quizQ = 0; S.quizScore = 0;
  S.quizAnswered = false; S.quizDone = false;
  S.idx = QUIZ_I;
  render();
}}

// ─── Main render ──────────────────────────────────────────────────
function render() {{
  updateNav();
  if (S.idx === 0) {{
    renderWelcome();
  }} else if (S.idx <= N) {{
    renderSlide(S.idx - 1);
  }} else if (S.idx === QUIZ_I) {{
    renderQuiz();
  }} else {{
    renderScore();
  }}
}}

// ─── Boot ─────────────────────────────────────────────────────────
document.getElementById("btnPrev").addEventListener("click", function() {{ go(-1); }});
document.getElementById("btnNext").addEventListener("click", function() {{
  if (S.idx === END_I) {{
    if (S.scorm) pipwerks.SCORM.quit();
    return;
  }}
  go(1);
  if (S.idx === END_I) {{
    renderScore();
    document.getElementById("progFill").style.width = "100%";
    document.getElementById("hProg").textContent = "Complete";
    document.getElementById("navMid").textContent = "Complete";
    document.getElementById("btnNext").innerHTML = 'Done ✓';
    document.getElementById("btnNext").className = "btn btn-success";
    document.getElementById("btnPrev").disabled = true;
  }}
}});
window.addEventListener("beforeunload", function() {{
  if (S.scorm) {{
    pipwerks.SCORM.set("cmi.core.lesson_location", String(S.idx));
    pipwerks.SCORM.quit();
  }}
}});

scormInit();
render();
</script>
</body>
</html>
"""


# ─── Main builder ───────────────────────────────────────────────────────────

def build_scorm(kb_path: str, module_id: str, output_path: str) -> None:
    print(f"\n📦 GovLearn SCORM Generator")
    print(f"   KB:     {kb_path}")
    print(f"   Module: {module_id}")
    print(f"   Output: {output_path}\n")

    with open(kb_path) as f:
        chunks = json.load(f)

    if not chunks:
        print("✗ knowledge_base.json is empty. Run generate_content.py first.")
        sys.exit(1)

    # Separate content slides from quiz
    quiz_chunk = None
    content_chunks = []
    for chunk in chunks:
        section_id = chunk.get("metadata", {}).get("section_id", "")
        if "quiz" in section_id.lower() or "quiz" in chunk.get("section", "").lower():
            quiz_chunk = chunk
        else:
            content_chunks.append(chunk)

    # Build slides list
    slides = []
    for chunk in content_chunks:
        section = chunk.get("section", "")
        slides.append({
            "section": section,
            "title": section,
            "content": chunk.get("content", ""),
        })

    # Parse quiz questions
    questions: list[dict] = []
    if quiz_chunk:
        questions = parse_quiz(quiz_chunk.get("content", ""))
        print(f"  ✓ Parsed {len(questions)} quiz questions")
    else:
        print("  ⚠ No quiz chunk found")

    # Course title
    first_section = slides[0]["section"] if slides else module_id
    course_title = f"GovLearn: {module_id.upper()} — {first_section}" if first_section else f"GovLearn: {module_id}"
    course_title = course_title[:120]
    print(f"  ✓ {len(slides)} content slides")

    # Fetch SCORM API wrapper
    print("\nFetching SCORM API wrapper...")
    scorm_api_js = fetch_scorm_api_js()

    # Build zip
    buf = BytesIO() if output_path == ":memory:" else None
    zip_target = buf or output_path

    print("\nBuilding SCORM package...")
    with zipfile.ZipFile(zip_target, "w", zipfile.ZIP_DEFLATED) as zf:

        # imsmanifest.xml
        zf.writestr("imsmanifest.xml", build_manifest(module_id, course_title))

        # js/scorm_api.js
        zf.writestr("js/scorm_api.js", scorm_api_js)

        # css/course.css
        zf.writestr("css/course.css", COURSE_CSS)

        # index.html (single SCO)
        zf.writestr("index.html", build_index_html(slides, questions, course_title, module_id))

        # slides/*.html (standalone reference pages)
        total = len(slides)
        for i, slide in enumerate(slides, 1):
            name = f"slides/slide_{str(i).zfill(3)}.html"
            zf.writestr(name, build_slide_html(slide, i, total, course_title))

        # quiz/quiz.html (standalone reference)
        if questions:
            zf.writestr("quiz/quiz.html", build_quiz_html(questions, course_title))

    if buf:
        return buf.getvalue()

    size_kb = os.path.getsize(output_path) // 1024
    print(f"\n✅ Package built: {output_path} ({size_kb} KB)")
    print(f"   → {len(slides)} slides + {'quiz' if questions else 'no quiz'}")
    print(f"   → Upload to Moodle: Course → Add activity → SCORM package")
    print(f"   → Upload to Moodle: {os.environ.get('MOODLE_URL','http://192.168.122.153:8080')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GovLearn SCORM 1.2 package generator")
    parser.add_argument("--kb", default="knowledge_base.json", help="Path to knowledge_base.json")
    parser.add_argument("--module-id", default="cyber-101", help="Module ID slug")
    parser.add_argument("--output", default=None, help="Output zip path (default: <module-id>.zip)")
    args = parser.parse_args()

    kb_path = args.kb
    if not os.path.isabs(kb_path):
        kb_path = os.path.join(os.path.dirname(__file__) or ".", kb_path)

    if not os.path.exists(kb_path):
        print(f"✗ Not found: {kb_path}")
        sys.exit(1)

    output = args.output or f"{args.module_id}.zip"
    if not os.path.isabs(output):
        output = os.path.join(os.path.dirname(__file__) or ".", output)

    build_scorm(kb_path, args.module_id, output)


if __name__ == "__main__":
    main()
