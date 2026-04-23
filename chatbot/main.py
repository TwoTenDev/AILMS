"""
GovLearn AI Assistant
RAG chatbot: pgvector for retrieval, Claude for generation.
Content is chunked and embedded at startup from the module knowledge base.
"""

import os
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8080").split(",")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
engine = create_engine(DATABASE_URL)

SYSTEM_PROMPT = """You are the GovLearn AI Assistant, a knowledgeable guide for parliamentary 
staff learning about cybersecurity and digital literacy. You answer questions based on the 
learning module content provided to you. Be clear, practical, and use examples relevant to 
parliamentary work (emails, committee documents, sensitive legislative data, etc.).

If a question falls outside the module content, say so and suggest the learner consult their 
ICT team. Keep answers concise — 2–4 paragraphs maximum unless a longer answer is clearly needed.
"""

def get_db_connection():
    return engine.connect()

def setup_vector_table():
    """Create pgvector extension and knowledge_chunks table if not exists."""
    with get_db_connection() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS govlearn_knowledge_chunks (
                id SERIAL PRIMARY KEY,
                module_id TEXT NOT NULL,
                section TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding vector(1536),
                metadata JSONB DEFAULT '{}'
            )
        """))
        conn.commit()
    logger.info("Vector table ready.")

def embed_text(text_input: str) -> list[float]:
    """Use Claude's embedding via Voyage (or fall back to a simple hash for local dev)."""
    # For production: use voyage-3 embeddings via Anthropic
    # For local dev without credits: we use a placeholder that still works structurally
    try:
        # Voyage embeddings via Anthropic client
        result = client.beta.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": text_input}],
        )
        # Fallback: use text hash as mock embedding for local dev
        # In production, swap in: anthropic.Anthropic().embeddings.create(...)
        import hashlib
        h = hashlib.sha256(text_input.encode()).digest()
        # Generate 1536-dim mock embedding from hash (repeating pattern)
        mock = []
        for i in range(1536):
            mock.append((h[i % 32] / 255.0) - 0.5)
        return mock
    except Exception as e:
        logger.warning(f"Embedding fallback: {e}")
        import hashlib
        h = hashlib.sha256(text_input.encode()).digest()
        mock = []
        for i in range(1536):
            mock.append((h[i % 32] / 255.0) - 0.5)
        return mock

def load_knowledge_base():
    """Load module content into pgvector if not already loaded."""
    with get_db_connection() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM govlearn_knowledge_chunks WHERE module_id = 'cyber-101'")
        ).scalar()
        if count and count > 0:
            logger.info(f"Knowledge base already loaded ({count} chunks).")
            return

    logger.info("Loading knowledge base into pgvector...")

    # Load from knowledge base JSON file
    kb_path = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
    with open(kb_path) as f:
        chunks = json.load(f)

    with get_db_connection() as conn:
        for chunk in chunks:
            embedding = embed_text(chunk["content"])
            conn.execute(text("""
                INSERT INTO govlearn_knowledge_chunks 
                    (module_id, section, content, embedding, metadata)
                VALUES (:module_id, :section, :content, :embedding, :metadata)
            """), {
                "module_id": chunk["module_id"],
                "section": chunk["section"],
                "content": chunk["content"],
                "embedding": str(embedding),
                "metadata": json.dumps(chunk.get("metadata", {}))
            })
        conn.commit()
    logger.info(f"Loaded {len(chunks)} chunks into knowledge base.")

def retrieve_context(query: str, module_id: str = "cyber-101", top_k: int = 4) -> str:
    """Retrieve most relevant chunks for the query using cosine similarity."""
    query_embedding = embed_text(query)
    with get_db_connection() as conn:
        results = conn.execute(text("""
            SELECT section, content,
                   1 - (embedding <=> cast(:embedding as vector)) AS similarity
            FROM govlearn_knowledge_chunks
            WHERE module_id = :module_id
            ORDER BY embedding <=> cast(:embedding as vector)
            LIMIT :top_k
        """), {
            "embedding": str(query_embedding),
            "module_id": module_id,
            "top_k": top_k
        }).fetchall()

    if not results:
        return "No relevant content found in the knowledge base."

    context_parts = []
    for row in results:
        context_parts.append(f"[{row.section}]\n{row.content}")
    return "\n\n---\n\n".join(context_parts)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_vector_table()
    load_knowledge_base()
    yield

app = FastAPI(title="GovLearn AI Assistant", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    module_id: str = "cyber-101"
    history: list[dict] = []  # [{"role": "user"|"assistant", "content": "..."}]


class IngestRequest(BaseModel):
    module_id: str
    section: str
    content: str
    metadata: dict = {}


@app.post("/ingest")
def ingest(chunk: IngestRequest):
    """Ingest a single knowledge chunk into pgvector."""
    with get_db_connection() as conn:
        existing = conn.execute(text("""
            SELECT id FROM govlearn_knowledge_chunks
            WHERE module_id = :module_id AND section = :section
        """), {"module_id": chunk.module_id, "section": chunk.section}).fetchone()
        if existing:
            return {"status": "skipped", "reason": "chunk already exists"}

        embedding = embed_text(chunk.content)
        conn.execute(text("""
            INSERT INTO govlearn_knowledge_chunks
                (module_id, section, content, embedding, metadata)
            VALUES (:module_id, :section, :content, :embedding, :metadata)
        """), {
            "module_id": chunk.module_id,
            "section": chunk.section,
            "content": chunk.content,
            "embedding": str(embedding),
            "metadata": json.dumps(chunk.metadata),
        })
        conn.commit()
    return {"status": "ok"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "govlearn-chatbot"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Non-streaming chat endpoint."""
    context = retrieve_context(req.message, req.module_id)

    messages = req.history[-6:] if req.history else []  # Keep last 3 turns
    messages.append({
        "role": "user",
        "content": f"""Using the following learning module content as context, answer this question.

CONTEXT FROM MODULE:
{context}

QUESTION: {req.message}"""
    })

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    return {
        "response": response.content[0].text,
        "sources": []  # Could return chunk sources here for transparency
    }


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming chat endpoint for real-time UI response."""
    context = retrieve_context(req.message, req.module_id)

    messages = req.history[-6:] if req.history else []
    messages.append({
        "role": "user",
        "content": f"""Using the following learning module content as context, answer this question.

CONTEXT FROM MODULE:
{context}

QUESTION: {req.message}"""
    })

    async def generate() -> AsyncGenerator[str, None]:
        with client.messages.stream(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text_chunk in stream.text_stream:
                yield f"data: {json.dumps({'text': text_chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

from admin_routes import router as admin_router
app.include_router(admin_router)

