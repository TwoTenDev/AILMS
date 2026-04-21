#!/usr/bin/env python3
"""
Generate the "Cybersecurity for Parliamentarians" module content using Claude.
Outputs: knowledge_base.json (for RAG) and module_outline.md (for H5P/Moodle import)
"""

import json
import os
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

def main():
    chunks = []
    outline_parts = [
        "# Cybersecurity for Parliamentarians\n",
        "## Module: CYBER-101 | GovLearn Parliamentary Learning Platform\n\n",
        "---\n\n"
    ]

    for section in SECTIONS:
        chunk = generate_section(section)
        chunks.append(chunk)
        outline_parts.append(f"## {chunk['section']}\n\n{chunk['content']}\n\n---\n\n")
        print(f"  ✓ Done ({len(chunk['content'])} chars)")

    # Save knowledge base for RAG
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
    with open(kb_path, "w") as f:
        json.dump(chunks, f, indent=2)
    print(f"\n✓ knowledge_base.json saved ({len(chunks)} chunks)")

    # Save full module outline as markdown
    outline_path = os.path.join(os.path.dirname(__file__), "..", "module_outline.md")
    with open(outline_path, "w") as f:
        f.write("".join(outline_parts))
    print(f"✓ module_outline.md saved")

if __name__ == "__main__":
    main()
