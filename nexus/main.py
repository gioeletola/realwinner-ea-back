"""
NEXUS News Aggregator — FastAPI backend
Proxies Anthropic AI enrichment requests so the API key stays server-side.
"""
import os
import json
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="NEXUS News Aggregator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


class Article(BaseModel):
    title: str
    description: str | None = ""


class EnrichRequest(BaseModel):
    articles: list[Article]
    category_label: str = "Mondo"


class EnrichedArticle(BaseModel):
    title: str
    summary: str


class EnrichResponse(BaseModel):
    articles: list[EnrichedArticle]
    pullQuote: str


@app.post("/api/enrich", response_model=EnrichResponse)
async def enrich(req: EnrichRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    top = req.articles[:6]
    articles_text = "\n\n".join(
        f"[{i}] Titolo: {a.title}\nDescrizione: {(a.description or '').strip()[:200]}"
        for i, a in enumerate(top)
    )

    prompt = (
        f"Sei il direttore editoriale di NEXUS, magazine di news premium italiano "
        f"con stile raffinato come The Atlantic.\n\n"
        f"Per ognuno dei {len(top)} articoli genera:\n"
        f"1. Titolo italiano elegante e magnetico (max 12 parole)\n"
        f"2. Sintesi italiana editoriale di qualità, 2 frasi (50-70 parole)\n\n"
        f"Poi una \"citazione editoriale\" riflessiva sullo scenario {req.category_label} (max 22 parole).\n\n"
        f"Articoli:\n{articles_text}\n\n"
        f"Rispondi SOLO in JSON valido (no markdown, no backtick):\n"
        f'{{\"articles\":[{{\"title\":\"...\",\"summary\":\"...\"}}],\"pullQuote\":\"...\"}}'
    )

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {resp.text[:200]}")

    data = resp.json()
    raw = data.get("content", [{}])[0].get("text", "")

    try:
        parsed = json.loads(raw.replace("```json", "").replace("```", "").strip())
        return EnrichResponse(
            articles=[EnrichedArticle(**a) for a in parsed.get("articles", [])],
            pullQuote=parsed.get("pullQuote", ""),
        )
    except Exception:
        fallback = [EnrichedArticle(title=a.title, summary=(a.description or "")[:160]) for a in top]
        return EnrichResponse(articles=fallback, pullQuote="")


# Serve the frontend
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
else:
    @app.get("/")
    async def root():
        return {"message": "NEXUS API is running. Place index.html in nexus/static/"}
