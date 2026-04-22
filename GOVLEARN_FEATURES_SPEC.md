# GovLearn — Feature Implementation Spec
## Two Features: PDF Ingestion + Moodle Auto-Course Creation

> **For the developer:** Read this entire document before writing any code.
> Work on Feature 1 first, test it end to end, then move to Feature 2.
> The existing stack is running at `192.168.122.153` — Moodle on `:8080`, chatbot on `:8000`.
> All work goes in `~/AILMS` on the dev VM, committed to the `develop` branch.

---

## Context

GovLearn is a Docker Compose stack: pgvector (postgres), Moodle LMS, and a FastAPI RAG chatbot powered by Claude. Currently `generate_content.py` uses hardcoded prompts to invent cybersecurity content. The goal is to replace this with a pipeline that:

1. Reads a real PDF policy document
2. Uses Claude to extract and structure it into learning content
3. Automatically creates a Moodle course from that content via the Moodle REST API

---

## Feature 1: PDF Policy Document Ingestion

### Goal
Replace hardcoded prompts in `generate_content.py` with Claude PDF reading. The script should accept a PDF file as input and generate grounded content from it.

### CLI Interface
```bash
# Current (keep working as fallback):
python generate_content.py

# New:
python generate_content.py --pdf /path/to/policy.pdf --module-id cyber-101 --title "Cybersecurity Policy"
```

### How It Works
1. Read the PDF file and encode it as base64
2. Send it to Claude with a structured prompt asking it to extract learning content
3. Claude returns JSON with sections, learning objectives, and quiz questions
4. Save as `knowledge_base.json` (for pgvector/RAG) and `module_outline.md` (for Moodle)

### Implementation

**File to modify:** `chatbot/generate_content.py`

**Add to requirements.txt:**
```
anthropic>=0.40.0  # already updated
```
No additional libraries needed — Claude handles PDF reading natively via the API.

**New generate_content.py structure:**

```python
#!/usr/bin/env python3
"""
GovLearn content generator.
Usage:
  python generate_content.py                          # use hardcoded prompts (demo)
  python generate_content.py --pdf policy.pdf \
    --module-id cyber-101 \
    --title "Cybersecurity for Parliamentarians"      # PDF ingestion mode
"""

import argparse
import base64
import json
import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# --- PDF MODE ---

PDF_EXTRACTION_PROMPT = """You are an instructional designer specialising in parliamentary education.

I'm giving you a policy document. Your job is to turn it into a structured e-learning module for parliamentary staff.

Return ONLY valid JSON with this exact structure (no markdown, no preamble):
{
  "title": "Module title derived from the document",
  "sections": [
    {
      "id": "section-slug",
      "section": "Section Title",
      "content": "350-400 words of learning content written in plain English for non-technical parliamentary staff. Ground everything in the actual policy document provided. Use concrete examples relevant to parliamentary work."
    }
  ],
  "quiz": [
    {
      "question": "Scenario-based question text",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "correct": "A",
      "explanation": "1-2 sentence explanation"
    }
  ]
}

Requirements:
- Generate 5-7 sections covering the key areas of the policy
- Write content for non-technical users (parliamentarians, clerks, administrative staff)
- Generate 5 scenario-based quiz questions grounded in the policy
- Every section must reference specific aspects of the uploaded document
- Tone: professional, accessible, practical
"""

def generate_from_pdf(pdf_path: str, module_id: str, title: str) -> list:
    """Read a PDF and use Claude to extract structured learning content."""
    print(f"Reading PDF: {pdf_path}")
    
    with open(pdf_path, "rb") as f:
        pdf_data = base64.standard_b64encode(f.read()).decode("utf-8")
    
    print("Sending to Claude for processing...")
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_data
                        }
                    },
                    {
                        "type": "text",
                        "text": PDF_EXTRACTION_PROMPT
                    }
                ]
            }
        ]
    )
    
    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    
    parsed = json.loads(raw)
    
    # Build chunks in the same format as the hardcoded mode
    chunks = []
    for section in parsed["sections"]:
        chunks.append({
            "module_id": module_id,
            "section": section["section"],
            "content": section["content"],
            "metadata": {"section_id": section["id"], "source": "pdf"}
        })
    
    # Add quiz as a chunk too
    quiz_content = "\n\n".join([
        f"Q: {q['question']}\n"
        f"A) {q['options']['A']}\nB) {q['options']['B']}\n"
        f"C) {q['options']['C']}\nD) {q['options']['D']}\n"
        f"Correct: {q['correct']}\nExplanation: {q['explanation']}"
        for q in parsed["quiz"]
    ])
    chunks.append({
        "module_id": module_id,
        "section": "Quiz Scenarios and Knowledge Check Questions",
        "content": quiz_content,
        "metadata": {"section_id": "quiz", "source": "pdf"}
    })
    
    return chunks, parsed.get("title", title)


# --- HARDCODED PROMPT MODE (keep existing SECTIONS and generate_section as-is) ---
# [Keep the existing SECTIONS list and generate_section() function here unchanged]


# --- SHARED OUTPUT ---

def save_outputs(chunks: list, module_id: str, title: str):
    """Save knowledge_base.json and module_outline.md"""
    # knowledge_base.json for RAG
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
    with open(kb_path, "w") as f:
        json.dump(chunks, f, indent=2)
    print(f"\n✓ knowledge_base.json saved ({len(chunks)} chunks)")

    # module_outline.md
    outline_parts = [f"# {title}\n\n## Module: {module_id.upper()} | GovLearn\n\n---\n\n"]
    for chunk in chunks:
        outline_parts.append(f"## {chunk['section']}\n\n{chunk['content']}\n\n---\n\n")
    
    outline_path = os.path.join(os.path.dirname(__file__), "..", "module_outline.md")
    with open(outline_path, "w") as f:
        f.write("".join(outline_parts))
    print(f"✓ module_outline.md saved")


def main():
    parser = argparse.ArgumentParser(description="GovLearn content generator")
    parser.add_argument("--pdf", help="Path to PDF policy document")
    parser.add_argument("--module-id", default="cyber-101", help="Module ID slug")
    parser.add_argument("--title", default="Cybersecurity for Parliamentarians", help="Module title")
    args = parser.parse_args()

    if args.pdf:
        chunks, title = generate_from_pdf(args.pdf, args.module_id, args.title or title)
    else:
        # Fallback to hardcoded prompts
        print("No PDF provided, using hardcoded prompts...")
        chunks = []
        for section in SECTIONS:
            chunk = generate_section(section)
            chunks.append(chunk)
        title = args.title

    save_outputs(chunks, args.module_id, title)
    print("\n✓ Done. Run the chatbot container to load into pgvector.")

if __name__ == "__main__":
    main()
```

### Testing Feature 1
```bash
# Test with a sample PDF (download any parliament cybersecurity policy PDF)
docker compose exec chatbot python generate_content.py \
  --pdf /app/sample_policy.pdf \
  --module-id cyber-101 \
  --title "Cybersecurity for Parliamentarians"

# Check output
cat chatbot/knowledge_base.json | python3 -m json.tool | head -50
cat module_outline.md | head -80

# Restart chatbot to reload knowledge base
docker compose restart chatbot

# Test chatbot with a question grounded in the policy
curl -X POST http://192.168.122.153:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the key password requirements in our policy?", "module_id": "cyber-101"}'
```

---

## Feature 2: Moodle REST API Auto-Course Creation

### Goal
After generating content, automatically create a fully structured Moodle course — sections, pages, and quizzes — via the Moodle REST API. No manual copy-pasting.

### CLI Interface
```bash
python create_moodle_course.py \
  --knowledge-base chatbot/knowledge_base.json \
  --module-id cyber-101 \
  --title "Cybersecurity for Parliamentarians"
```

### Prerequisites
You need a Moodle web services token. Set this up once:

1. Log into Moodle as admin → Site Administration → Plugins → Web Services → Overview
2. Enable web services (if not already on)
3. Enable REST protocol
4. Create an external service called "GovLearn API" with these functions enabled:
   - `core_course_create_courses`
   - `core_course_create_sections` (or edit sections)
   - `mod_page_add_module` (or `core_course_edit_module`)
   - `mod_quiz_add_quiz`
   - `mod_quiz_add_question` 
5. Create a token for admin user → copy it to `.env` as `MOODLE_TOKEN`

**Add to .env:**
```
MOODLE_TOKEN=your_token_here
MOODLE_URL=http://192.168.122.153:8080
```

### Implementation

**New file:** `chatbot/create_moodle_course.py`

```python
#!/usr/bin/env python3
"""
GovLearn Moodle Course Creator
Creates a Moodle course from knowledge_base.json via the Moodle REST API.

Usage:
  python create_moodle_course.py \
    --knowledge-base chatbot/knowledge_base.json \
    --module-id cyber-101 \
    --title "Cybersecurity for Parliamentarians"
"""

import argparse
import json
import os
import requests

MOODLE_URL = os.environ.get("MOODLE_URL", "http://localhost:8080")
MOODLE_TOKEN = os.environ["MOODLE_TOKEN"]


def moodle_api(function: str, params: dict) -> dict:
    """Make a Moodle REST API call."""
    url = f"{MOODLE_URL}/webservice/rest/server.php"
    params.update({
        "wstoken": MOODLE_TOKEN,
        "wsfunction": function,
        "moodlewsrestformat": "json"
    })
    response = requests.post(url, data=params)
    result = response.json()
    if isinstance(result, dict) and "exception" in result:
        raise Exception(f"Moodle API error: {result.get('message', result)}")
    return result


def create_course(title: str, module_id: str) -> int:
    """Create a new Moodle course and return its ID."""
    print(f"Creating course: {title}")
    result = moodle_api("core_course_create_courses", {
        "courses[0][fullname]": title,
        "courses[0][shortname]": module_id,
        "courses[0][categoryid]": 1,  # Default category
        "courses[0][summary]": f"GovLearn module: {title}",
        "courses[0][format]": "topics",
        "courses[0][numsections]": 10,
        "courses[0][visible]": 1,
    })
    course_id = result[0]["id"]
    print(f"  ✓ Course created (ID: {course_id})")
    return course_id


def add_page(course_id: int, section: int, title: str, content: str) -> int:
    """Add a page resource to a course section."""
    result = moodle_api("core_course_edit_module", {
        "action": "add",
        "modulename": "page",
        "courseid": course_id,
        "section": section,
        "page[name]": title,
        "page[content]": content.replace("\n", "<br>"),
        "page[contentformat]": 1,  # HTML
    })
    return result.get("cmid", 0)


def add_quiz(course_id: int, section: int, chunks: list) -> None:
    """Add a quiz with multiple choice questions."""
    # Find quiz chunk
    quiz_chunks = [c for c in chunks if c["metadata"].get("section_id") == "quiz"]
    if not quiz_chunks:
        print("  ! No quiz content found, skipping quiz creation")
        return

    print("  Creating quiz...")
    # Create the quiz activity
    quiz_result = moodle_api("core_course_edit_module", {
        "action": "add",
        "modulename": "quiz",
        "courseid": course_id,
        "section": section,
        "quiz[name]": "Knowledge Check",
        "quiz[intro]": "Test your understanding of the module content.",
        "quiz[introformat]": 1,
        "quiz[timelimit]": 0,
        "quiz[attempts]": 0,  # Unlimited attempts
        "quiz[grademethod]": 1,
        "quiz[shuffleanswers]": 1,
    })
    print(f"  ✓ Quiz created")


def create_moodle_course(kb_path: str, module_id: str, title: str):
    """Main function: read knowledge base and create Moodle course."""
    with open(kb_path) as f:
        chunks = json.load(f)

    if not chunks:
        print("Error: knowledge_base.json is empty. Run generate_content.py first.")
        return

    # Create the course
    course_id = create_course(title, module_id)

    # Add each section as a page
    content_chunks = [c for c in chunks if c["metadata"].get("section_id") != "quiz"]
    for i, chunk in enumerate(content_chunks, start=1):
        print(f"  Adding section {i}: {chunk['section']}")
        try:
            add_page(course_id, i, chunk["section"], chunk["content"])
            print(f"    ✓ Page added")
        except Exception as e:
            print(f"    ! Failed: {e}")

    # Add quiz as final section
    quiz_section = len(content_chunks) + 1
    try:
        add_quiz(course_id, quiz_section, chunks)
    except Exception as e:
        print(f"  ! Quiz creation failed: {e}")

    print(f"\n✓ Course created successfully!")
    print(f"  View at: {MOODLE_URL}/course/view.php?id={course_id}")


def main():
    parser = argparse.ArgumentParser(description="Create a Moodle course from GovLearn content")
    parser.add_argument("--knowledge-base", default="chatbot/knowledge_base.json")
    parser.add_argument("--module-id", default="cyber-101")
    parser.add_argument("--title", default="Cybersecurity for Parliamentarians")
    args = parser.parse_args()

    create_moodle_course(args.knowledge_base, args.module_id, args.title)


if __name__ == "__main__":
    main()
```

**Add to requirements.txt:**
```
requests>=2.31.0
```

### Important Notes on Moodle REST API

The Moodle REST API for adding modules (`mod_page`, `mod_quiz`) can be finicky — the exact function names depend on the Moodle version and which plugins are installed. If `core_course_edit_module` doesn't work, the fallback approach is:

1. Use `core_course_create_courses` to create the course ✓ (this always works)
2. Use `core_course_create_sections` to create sections ✓
3. For page content, try `mod_page_view_page` or check available functions with:
   ```bash
   curl "http://192.168.122.153:8080/webservice/rest/server.php?wstoken=TOKEN&wsfunction=core_webservice_get_site_info&moodlewsrestformat=json"
   ```

**Check available functions:**
```bash
curl "http://192.168.122.153:8080/webservice/rest/server.php" \
  -d "wstoken=YOUR_TOKEN&wsfunction=core_webservice_get_site_info&moodlewsrestformat=json"
```

### Testing Feature 2
```bash
# Set env vars
export MOODLE_TOKEN=your_token
export MOODLE_URL=http://192.168.122.153:8080

# Run course creator
python chatbot/create_moodle_course.py \
  --knowledge-base chatbot/knowledge_base.json \
  --module-id cyber-101 \
  --title "Cybersecurity for Parliamentarians"

# Open Moodle and verify the course was created
# http://192.168.122.153:8080
```

---

## Full End-to-End Flow (Once Both Features Built)

```bash
# 1. Generate content from PDF
docker compose exec chatbot python generate_content.py \
  --pdf /app/fiji_cyber_policy.pdf \
  --module-id cyber-101

# 2. Restart chatbot to load new knowledge base into pgvector
docker compose restart chatbot

# 3. Create the Moodle course automatically
python chatbot/create_moodle_course.py \
  --knowledge-base chatbot/knowledge_base.json \
  --module-id cyber-101 \
  --title "Cybersecurity for Parliamentarians"

# 4. Embed chatbot widget in the Moodle course (HTML block iframe)
# URL: http://192.168.122.153:8000/chat?module_id=cyber-101
```

---

## Commit Strategy

```bash
# After Feature 1 working:
git add chatbot/generate_content.py chatbot/requirements.txt
git commit -m "feat: PDF policy document ingestion via Claude"
git push origin develop

# After Feature 2 working:
git add chatbot/create_moodle_course.py chatbot/requirements.txt .env.example
git commit -m "feat: Moodle REST API auto-course creation"
git push origin develop
```

---

## What NOT to Change
- `chatbot/main.py` — RAG chatbot, leave untouched
- `docker-compose.yml` — stack config, leave untouched
- `chatbot/Dockerfile` — leave untouched
- `.env` — add `MOODLE_TOKEN` and `MOODLE_URL` but don't change existing vars

---

*GovLearn — TwoTen Consult*
