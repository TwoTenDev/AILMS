# GovLearn Next Phase — Claude Code Spec

## Context

GovLearn is an AI-powered LMS (AILMS) targeting parliamentary and government clients.
The core pipeline is working and committed to `develop`:

```
PDF policy doc → generate_content.py → knowledge_base.json
                                      → create_moodle_course.py → Moodle course (pages + quiz)
```

Both features are tested and working. The next phase is improving the **visual quality
and portability** of generated courses.

---

## Stack

- **VM:** `192.168.122.153`
- **Repo:** `git@github.com:TwoTenDev/AILMS.git`, branch: `develop`
- **Working dir:** `~/AILMS`
- **Docker services:** postgres (pgvector), Moodle (port 8080), FastAPI chatbot (port 8000)
- **Moodle token:** `d687610cf5075667f4b0c79dea1957c0`
- **Moodle URL:** `http://192.168.122.153:8080`
- **Key files:**
  - `chatbot/generate_content.py` — PDF ingestion + content generation
  - `chatbot/create_moodle_course.py` — Moodle course builder
  - `chatbot/knowledge_base.json` — generated content store
  - `moodle_plugins/local_govlearn/` — custom Moodle plugin for page/quiz creation

---

## Decision Point

Before building, confirm with the user which route to take:

### Option A: SCORM Package Generator (Recommended)

Build `chatbot/generate_scorm.py` that reads `knowledge_base.json` and outputs a
standards-compliant SCORM 1.2 zip package with rich HTML5 content.

**Why:** LMS-agnostic (works on Moodle, TalentLMS, Docebo, Canvas, anything),
full visual control, no additional licences, fully automated.

**What a SCORM package contains:**
```
course.zip
├── imsmanifest.xml          # LMS metadata (course structure)
├── js/
│   └── scorm_api.js         # pipwerks SCORM API wrapper (MIT, open source)
├── css/
│   └── course.css           # course styling
├── slides/
│   ├── slide_001.html       # one HTML file per knowledge_base chunk
│   ├── slide_002.html
│   └── ...
├── quiz/
│   └── quiz.html            # interactive quiz with SCORM score reporting
└── index.html               # course shell (navigation, progress bar)
```

**Implementation steps:**

1. **Download pipwerks SCORM API wrapper:**
   ```
   https://raw.githubusercontent.com/pipwerks/scorm-api-wrapper/master/src/JavaScript/SCORM_API_wrapper.js
   ```

2. **Build `imsmanifest.xml` generator** — template with course title, identifier,
   one `<item>` per slide + one for quiz

3. **Build HTML slide template** — rich, visually impressive:
   - Dark header bar with course/section title
   - Content area with styled callouts, icon boxes, scenario cards
   - Use Font Awesome (CDN) for icons
   - CSS animations for section entry (fade in, slide up)
   - Previous/Next navigation
   - Progress indicator (e.g. "Page 3 of 7")
   - Mobile responsive

4. **Build quiz.html** — interactive multiple choice:
   - One question at a time
   - Animated feedback on answer (green tick / red cross)
   - Score tracking via SCORM API (report `cmi.core.score.raw` and `cmi.core.lesson_status`)
   - Summary screen at end

5. **Build `generate_scorm.py`:**
   ```
   Usage: python generate_scorm.py --kb knowledge_base.json --module-id cyber-101
   Output: cyber-101.zip (SCORM package ready to upload to any LMS)
   ```

6. **Optionally: auto-upload to Moodle** via REST API:
   - `core_course_create_courses` (already working)
   - Upload zip as a SCORM activity using `mod_scorm` module

**Visual quality target:**
Think Articulate Rise — clean, modern, card-based layout. Not a PowerPoint.
Each slide should feel like a designed page, not a wall of text.

---

### Option B: Moodle-Native H5P Enrichment

Stay within Moodle but generate H5P interactive content instead of plain pages.

**Why:** Simpler, no new file format to learn, H5P already installed in most Moodle instances.

**H5P content types to use:**
- `Course Presentation` — slide-based, supports animations
- `Interactive Video` — if we add video later
- `Question Set` — better quiz experience than native Moodle quiz

**Implementation:**
H5P has a REST API (`hvp` endpoints in Moodle) but it's poorly documented.
The easier route is generating H5P JSON packages directly and uploading via the
Moodle file API. H5P packages are zip files containing JSON + assets.

**Downside:** Still Moodle-only, H5P API is complex, less visual control than SCORM.

---

## Whichever Option is Chosen

### Also implement: Self-enrolment on generated courses

Update `create_moodle_course.py` to enable self-enrolment automatically:

```python
def enable_self_enrolment(course_id: int) -> None:
    """Enable self-enrolment on the course so users can enrol without admin."""
    # Get enrolment methods
    result = call("core_enrol_get_course_enrolment_methods", courseid=course_id)
    # Enable self enrolment via DB if not available via API
```

Via DB (more reliable):
```sql
INSERT INTO mdl_enrol (enrol, status, courseid, sortorder, name)
VALUES ('self', 0, {course_id}, 0, 'Self enrolment')
ON CONFLICT DO NOTHING;
```

### Also implement: pgvector ingestion

After course creation, load `knowledge_base.json` into pgvector for the chatbot.
This is partially implemented in `chatbot/main.py` — check the existing ingestion
endpoint and call it after course creation:

```python
def ingest_to_pgvector(kb_path: str) -> None:
    """POST knowledge_base.json chunks to the chatbot ingestion endpoint."""
    import requests
    with open(kb_path) as f:
        chunks = json.load(f)
    for chunk in chunks:
        requests.post("http://localhost:8000/ingest", json=chunk)
```

---

## Testing

After implementation, run the full pipeline:

```bash
# Inside chatbot container
docker exec -it ailms-chatbot-1 bash

# Full pipeline test
python generate_content.py --pdf cyber_policy.pdf --module-id cyber-101
python generate_scorm.py --kb knowledge_base.json --module-id cyber-101
# → outputs cyber-101.zip

# Verify zip structure
python -c "import zipfile; z=zipfile.ZipFile('cyber-101.zip'); print('\n'.join(z.namelist()))"
```

Then upload `cyber-101.zip` to Moodle manually:
- Course → Add activity → SCORM package → upload zip → save
- Log in as a student, enrol, take the course
- Verify completion is tracked

---

## Notes for Claude Code

- Keep all generated files in `~/AILMS/chatbot/`
- The SCORM spec to follow is SCORM 1.2 (not 2004) — wider LMS compatibility
- pipwerks wrapper handles the LMS API abstraction — use it, don't reinvent
- For HTML slide design, prioritise readability and professionalism over flashiness
- The parliamentary audience is professional — avoid anything that looks like a game
- Test the zip by uploading to `http://192.168.122.153:8080` before declaring done
- Commit all new files to `develop` branch when complete
