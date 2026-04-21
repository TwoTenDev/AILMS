# GovLearn – Parliamentary Learning Platform

> AI-powered LMS for Pacific Island legislatures. Built on Moodle + pgvector + Claude.
> A TwoTen Consult product — [twotenconsult.com](https://twotenconsult.com)

---

## Architecture

```
Docker Compose
├── Moodle 4.5 (bitnami/moodle) — LMS
├── PostgreSQL 16 + pgvector — database + vector store
├── GovLearn Chatbot (FastAPI + Claude API) — RAG AI assistant
└── Caddy — reverse proxy + auto SSL (production only)
```

The chatbot embeds into Moodle as an HTML block (iframe). Content is chunked,
embedded via pgvector, and retrieved per-query for grounded, module-specific answers.

---

## Local Development

### Prerequisites
- Docker + Docker Compose
- An Anthropic API key (`sk-ant-...`)

### Setup

```bash
git clone https://github.com/TwoTenDev/govlearn.git
cd govlearn

# Copy and fill in your env vars
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY at minimum

# Start the stack
docker compose up -d

# Generate module content (run once, requires API key)
docker compose exec chatbot python generate_content.py
```

Moodle will be available at **http://localhost:8080** after ~2–3 minutes first boot
(it runs database migrations on startup).

Admin credentials are set in `.env` (default: `admin` / `GovLearn2025!`).

---

## Generate Module Content

The `generate_content.py` script calls Claude to write all module sections and
saves them as:

- `chatbot/knowledge_base.json` — loaded into pgvector for RAG
- `module_outline.md` — full module text for H5P/Moodle import

```bash
docker compose exec chatbot python generate_content.py
```

The chatbot service auto-loads `knowledge_base.json` on startup if the table is empty.

---

## Embedding the Chatbot in Moodle

1. Log in to Moodle as admin
2. Go to the **Cybersecurity for Parliamentarians** course
3. Turn editing on → Add a block → **HTML block**
4. Paste this iframe into the block:

```html
<iframe
  src="http://localhost:8000/chat"
  width="100%"
  height="520"
  frameborder="0"
  style="border-radius:12px; border:1px solid #e5e7eb;">
</iframe>
```

For production, replace `localhost:8000` with `https://yourdomain.com/api/chat`.

Alternatively, serve `chat_widget.html` as a static file from the chatbot container
and point the iframe there.

---

## Production Deployment (Hetzner)

```bash
# On the server
git clone https://github.com/TwoTenDev/govlearn.git
cd govlearn
cp .env.example .env
# Edit .env: set DOMAIN, strong passwords, ANTHROPIC_API_KEY

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose exec chatbot python generate_content.py
```

Caddy handles SSL automatically via Let's Encrypt. Point your DNS A record to
the server IP before starting.

---

## White-Labelling for Other Parliaments

Each deployment is independent. To deploy for a new parliament:
1. Clone the repo or use a new branch per client
2. Update `MOODLE_SITE_NAME` in `.env`
3. Replace module content by editing `generate_content.py` prompts
4. Run `generate_content.py` to populate the new knowledge base
5. Deploy on a new VPS

The chatbot is module-scoped (`module_id` parameter) — multiple modules can
coexist in the same pgvector table.

---

## Project Structure

```
govlearn/
├── docker-compose.yml          # Local dev
├── docker-compose.prod.yml     # Production overrides
├── .env.example
├── caddy/
│   └── Caddyfile
├── chatbot/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # FastAPI app (RAG + Claude)
│   ├── generate_content.py     # AI content generation script
│   ├── chat_widget.html        # Embeddable chatbot UI
│   └── knowledge_base.json     # Generated — do not edit manually
├── moodle-data/                # Moodle files (gitignored)
├── moodledata/                 # Moodle user data (gitignored)
└── postgres-data/              # DB data (gitignored)
```

---

## Roadmap

- [ ] H5P module export for direct Moodle import
- [ ] CSV bulk user import for parliament onboarding
- [ ] Multi-module support (Digital Literacy, Open Parliament)
- [ ] Admin dashboard for usage analytics
- [ ] Automated backups to S3/Hetzner Object Storage
- [ ] SCORM-compliant module packaging

---

*GovLearn is a TwoTen Consult platform product. For licensing and deployment
enquiries: hello@twotenconsult.com*
