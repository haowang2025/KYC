from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .kg_client import KGClient
from .triage_engine import TriageEngine, TriageInput

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
FRONTEND_INDEX = FRONTEND_DIR / "index.html"

kg = KGClient()
engine = TriageEngine()

app = FastAPI(
    title="ClearCheck",
    description="Merchant Risk Triage Agent — Green / Yellow / Red decisions with evidence",
    version=os.getenv("CLEARCHECK_VERSION", "0.2.0"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TriageRequest(BaseModel):
    entity_name: str = Field(..., description="Name of the merchant / supplier / entity")
    country: str = Field(..., description="Country of registration or operation")
    entity_type: str = Field("merchant", description="merchant | supplier | buyer | seller")
    address: str = Field("", description="Physical address (optional)")
    registration_id: str = Field("", description="Company registration number (optional)")
    payment_currency: str = Field("", description="Payment currency code (optional)")
    goods_category: str = Field("", description="Type of goods/services (optional)")
    transaction_amount: float = Field(0.0, description="Transaction amount in USD (optional)")
    counterparty: str = Field("", description="Other party in the transaction (optional)")


class ChatRequest(BaseModel):
    query: str = Field(..., description="Natural language query about an entity to check")


@app.get("/")
async def root():
    return FileResponse(FRONTEND_INDEX)


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "ClearCheck", "kg": "connected" if kg.is_connected else "fallback"}


@app.post("/chat")
async def chat(req: ChatRequest):
    normalized = await engine.parse_query(req.query)

    inp = TriageInput(
        entity_name=normalized.canonical_name,
        country=normalized.country_normalized,
        entity_type=normalized.entity_type or "merchant",
        payment_currency=normalized.payment_currency,
        goods_category=normalized.goods_category,
        transaction_amount=normalized.transaction_amount,
    )

    search_names = [normalized.canonical_name] + normalized.aliases
    search_names = list(dict.fromkeys(search_names))
    kg_result = kg.search_multi(search_names, inp.country)

    result = await engine.evaluate(inp, kg_result)
    best = kg_result.best_match

    return {
        "normalized": {
            "canonical_name": normalized.canonical_name,
            "aliases": normalized.aliases[:5],
            "country": normalized.country_normalized,
            "entity_type": normalized.entity_type,
            "transaction_amount": normalized.transaction_amount,
            "goods_category": normalized.goods_category,
            "notes": normalized.notes,
        },
        "kg": {
            "has_match": kg_result.has_matches,
            "source": kg_result.source,
            "match_name": best.name if best else None,
            "match_country": best.country if best else None,
            "match_labels": best.risk_labels if best else [],
            "match_confidence": best.confidence if best else 0,
            "variant_count": len(search_names),
        },
        "result": result.to_dict(),
    }


@app.post("/triage")
async def triage(req: TriageRequest):
    if req.entity_name and req.country:
        normalized = await engine.parse_query("", name=req.entity_name, country=req.country)
    else:
        normalized = await engine.parse_query(req.entity_name)

    inp = TriageInput(
        entity_name=normalized.canonical_name,
        country=normalized.country_normalized or req.country,
        entity_type=normalized.entity_type or req.entity_type,
        address=req.address,
        registration_id=req.registration_id,
        payment_currency=normalized.payment_currency or req.payment_currency,
        goods_category=normalized.goods_category or req.goods_category,
        transaction_amount=normalized.transaction_amount or req.transaction_amount,
        counterparty=req.counterparty,
    )

    search_names = [normalized.canonical_name] + normalized.aliases
    search_names = list(dict.fromkeys(search_names))
    kg_result = kg.search_multi(search_names, inp.country)

    result = await engine.evaluate(inp, kg_result)
    return result.to_dict()

