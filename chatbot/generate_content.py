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

def generate_from_pdf(pdf_path: str, module_id: str, title: str) -> tuple:
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

    chunks = []
    for section in parsed["sections"]:
        chunks.append({
            "module_id": module_id,
            "section": section["section"],
            "content": section["content"],
            "metadata": {"section_id": section["id"], "source": "pdf"}
        })

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


# --- HARDCODED PROMPT MODE ---

MODULE_ID = "cyber-101"

SECTIONS = [
    {
        "id": "intro",
        "section": "Introduction: Why Cybersecurity Matters in Parliament",
        "prompt": """Write a 300-word introduction to a cybersecurity module for parliamentary staff
        in a Pacific Island nation. Cover: why parliament is a target (sensitive legislation,
        committee deliberations, constituent data), real-world examples of parliament cyberattacks
        (generic/anonymised), and what this module will teach. Tone: professional but accessible,
        not technical jargon. Written as module content, not as instructions."""
    },
    {
        "id": "phishing",
        "section": "Recognising Phishing and Social Engineering",
        "prompt": """Write 400 words of learning content on phishing and social engineering attacks
        for parliamentary staff. Cover: what phishing emails look like, spear-phishing targeting
        MPs and senior officials, social engineering via phone/WhatsApp, red flags to watch for
        (urgency, unusual sender, suspicious links), and 2 realistic example scenarios set in a
        parliamentary context (e.g. fake IT helpdesk email, fake journalist contact). Include a
        short checklist of warning signs. Written as module content."""
    },
    {
        "id": "passwords",
        "section": "Password Security and Multi-Factor Authentication",
        "prompt": """Write 350 words of learning content on password security and MFA for
        parliamentary staff. Cover: why weak passwords are dangerous, how to create strong
        passphrases, password managers (what they are and why to use one), what MFA is and
        how to set it up on common platforms (email, WhatsApp, government systems), and why
        SMS-based MFA is better than nothing but authenticator apps are better.
        Written as practical module content for non-technical users."""
    },
    {
        "id": "devices",
        "section": "Secure Use of Devices and Networks",
        "prompt": """Write 350 words of learning content on secure device and network use for
        parliamentary staff. Cover: keeping devices updated, locking screens, risks of public
        Wi-Fi and using a VPN, dangers of USB drives from unknown sources, BYOD risks in a
        parliamentary setting, and secure disposal of old devices with sensitive data.
        Include a specific scenario about a parliamentary committee member working remotely
        during a recess. Written as module content."""
    },
    {
        "id": "data",
        "section": "Handling Sensitive Parliamentary Data",
        "prompt": """Write 350 words of learning content on handling sensitive data in a
        parliamentary context. Cover: types of sensitive data in parliament (draft legislation,
        committee in-camera sessions, constituent casework, budget documents), classification
        principles (what to share vs. not), risks of cloud storage for sensitive docs,
        safe file sharing practices, and what to do if a data breach is suspected.
        Written as practical module content."""
    },
    {
        "id": "incident",
        "section": "What to Do When Something Goes Wrong",
        "prompt": """Write 300 words of learning content on incident response for parliamentary
        staff. Cover: recognising that something has gone wrong (suspicious account activity,
        ransomware screen, missing files), the golden rule of not turning off the device,
        who to contact immediately (parliamentary ICT team), not to panic or try to fix it
        yourself, preserving evidence, and the importance of reporting near-misses too.
        Include a simple 5-step response checklist. Written as module content."""
    },
    {
        "id": "quiz-scenarios",
        "section": "Quiz Scenarios and Knowledge Check Questions",
        "prompt": """Write 5 multiple-choice quiz questions for a cybersecurity module aimed at
        parliamentary staff. Each question should be scenario-based (not abstract). Format each as:
        Q: [question]
        A) [option]
        B) [option]
        C) [option]
        D) [option]
        Correct: [letter]
        Explanation: [1-2 sentence explanation]

        Cover one question each on: phishing recognition, password hygiene, MFA,
        public Wi-Fi risks, and incident reporting."""
    }
]

def generate_section(section: dict) -> dict:
    print(f"Generating: {section['section']}...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": section["prompt"]}]
    )
    content = response.content[0].text
    return {
        "module_id": MODULE_ID,
        "section": section["section"],
        "content": content,
        "metadata": {"section_id": section["id"]}
    }


# --- SHARED OUTPUT ---

def save_outputs(chunks: list, module_id: str, title: str):
    """Save knowledge_base.json and module_outline.md"""
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
    with open(kb_path, "w") as f:
        json.dump(chunks, f, indent=2)
    print(f"\n✓ knowledge_base.json saved ({len(chunks)} chunks)")

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
        chunks, title = generate_from_pdf(args.pdf, args.module_id, args.title)
    else:
        print("No PDF provided, using hardcoded prompts...")
        chunks = []
        for section in SECTIONS:
            chunk = generate_section(section)
            chunks.append(chunk)
            print(f"  ✓ Done ({len(chunk['content'])} chars)")
        title = args.title

    save_outputs(chunks, args.module_id, title)
    print("\n✓ Done. Run the chatbot container to load into pgvector.")

if __name__ == "__main__":
    main()
