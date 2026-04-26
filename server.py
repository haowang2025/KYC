"""
ClearCheck — FastAPI Server + CLI Runner

Two entry points:
  1. FastAPI server:  uvicorn server:app
  2. CLI one-shot:    python server.py --name "Parsian Bank" --country "Iran"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional

from kg_client import KGClient
from triage_engine import TriageEngine, TriageInput, NormalizedEntity

# ── Init ──────────────────────────────────────────────────────────────────

kg = KGClient()
engine = TriageEngine()

# ── FastAPI ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="ClearCheck",
    description="Merchant Risk Triage Agent — Green / Yellow / Red decisions with evidence",
    version="0.1.0",
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

@app.get("/")
async def root():
    return FileResponse(os.path.join(os.path.dirname(__file__), "frontend", "index.html"))

app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend")), name="static")


class ChatRequest(BaseModel):
    query: str = Field(..., description="Natural language query about an entity to check")


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "ClearCheck", "kg": "connected" if kg._arango_db else "fallback"}


@app.post("/chat")
async def chat(req: ChatRequest):
    """Natural language triage — the frontend sends free-text queries here."""
    # Step 1: Parse
    normalized = await engine.parse_query(req.query)

    inp = TriageInput(
        entity_name=normalized.canonical_name,
        country=normalized.country_normalized,
        entity_type=normalized.entity_type or "merchant",
        payment_currency=normalized.payment_currency,
        goods_category=normalized.goods_category,
        transaction_amount=normalized.transaction_amount,
    )

    # Step 2: KG search
    search_names = [normalized.canonical_name] + normalized.aliases
    search_names = list(dict.fromkeys(search_names))
    kg_result = kg.search_multi(search_names, inp.country)

    # Step 3-5: Evaluate
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
    """Run merchant risk triage and return structured result."""
    # Step 1: LLM Parse & Normalize
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

    # Step 2: KG search with all name variants
    search_names = [normalized.canonical_name] + normalized.aliases
    search_names = list(dict.fromkeys(search_names))
    kg_result = kg.search_multi(search_names, inp.country)

    # Steps 3-5: Evaluate and generate report
    result = await engine.evaluate(inp, kg_result)
    return result.to_dict()


# ── CLI Mode ──────────────────────────────────────────────────────────────

async def run_triage(query_text: str = "", name: str = "", country: str = "",
                     amount: float = 0.0, currency: str = "", goods: str = ""):
    """Run a single triage from any input format."""
    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║           C L E A R C H E C K             ║")
    print("  ║     Merchant Risk Triage Agent             ║")
    print("  ╚═══════════════════════════════════════════╝")
    print()

    # Step 1: LLM Parse & Normalize
    print(f"  Step 1 · Parsing query via LLM...")
    if query_text:
        print(f"           Input:      \"{query_text}\"")
        normalized = await engine.parse_query(query_text)
    else:
        print(f"           Input:      {name} / {country}")
        normalized = await engine.parse_query("", name=name, country=country)

    print(f"           Canonical:  {normalized.canonical_name}")
    if normalized.aliases:
        print(f"           Aliases:    {', '.join(normalized.aliases[:4])}")
    print(f"           Country:    {normalized.country_normalized}")
    if normalized.transaction_amount:
        print(f"           Amount:     ${normalized.transaction_amount:,.0f}")
    if normalized.goods_category:
        print(f"           Goods:      {normalized.goods_category}")
    if normalized.notes:
        print(f"           Notes:      {normalized.notes}")

    inp = TriageInput(
        entity_name=normalized.canonical_name,
        country=normalized.country_normalized or country,
        entity_type=normalized.entity_type or "merchant",
        payment_currency=normalized.payment_currency or currency,
        goods_category=normalized.goods_category or goods,
        transaction_amount=normalized.transaction_amount or amount,
    )
    print()

    # Step 2: KG search with all name variants
    print(f"  Step 2 · Searching knowledge graph...")
    search_names = [normalized.canonical_name] + normalized.aliases
    search_names = list(dict.fromkeys(search_names))
    print(f"           Searching {len(search_names)} name variants...")
    kg_result = kg.search_multi(search_names, inp.country)

    if kg_result.has_matches:
        best = kg_result.best_match
        print(f"           ⚡ MATCH FOUND: {best.name} ({best.country})")
        print(f"              Labels: {best.risk_labels}")
        print(f"              Confidence: {best.confidence:.0%}")
        print(f"              Source: {kg_result.source}")
    else:
        print(f"           ✓ No matching entities found ({kg_result.source})")
    print()

    # Step 3-4: Evaluate
    print(f"  Step 3 · Evaluating risk signals...")
    result = await engine.evaluate(inp, kg_result)

    for s in result.signals:
        sev_icon = {"critical": "🔴", "elevated": "🟡", "minor": "⚪"}[s.severity]
        print(f"           {sev_icon} [{s.code}] {s.description}")
    print()

    print(f"  Step 4 · Decision logic applied")
    emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[result.decision]
    print(f"           → {emoji} {result.decision} — {result.decision_label}")
    print()

    # Step 5: Full report
    print(f"  Step 5 · Generating report...")
    print(result.to_report())


async def run_chat():
    """Interactive chat loop — talk to ClearCheck in natural language."""
    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║           C L E A R C H E C K             ║")
    print("  ║     Merchant Risk Triage Agent             ║")
    print("  ╚═══════════════════════════════════════════╝")
    print()
    print("  💬 Chat mode — describe who you want to check.")
    print("     Type 'quit' to exit.\n")

    while True:
        try:
            query = input("  You > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in ("quit", "exit", "q"):
            print("\n  Goodbye!")
            break

        print()
        print(f"  Step 1 · Parsing query via LLM...")
        print(f"           Input:      \"{query}\"")
        normalized = await engine.parse_query(query)
        print(f"           Canonical:  {normalized.canonical_name}")
        if normalized.aliases:
            print(f"           Aliases:    {', '.join(normalized.aliases[:4])}")
        print(f"           Country:    {normalized.country_normalized}")
        if normalized.transaction_amount:
            print(f"           Amount:     ${normalized.transaction_amount:,.0f}")
        if normalized.notes:
            print(f"           Notes:      {normalized.notes}")

        inp = TriageInput(
            entity_name=normalized.canonical_name,
            country=normalized.country_normalized,
            entity_type=normalized.entity_type or "merchant",
            payment_currency=normalized.payment_currency,
            goods_category=normalized.goods_category,
            transaction_amount=normalized.transaction_amount,
        )
        print()

        print(f"  Step 2 · Searching knowledge graph...")
        search_names = [normalized.canonical_name] + normalized.aliases
        search_names = list(dict.fromkeys(search_names))
        print(f"           Searching {len(search_names)} name variants...")
        kg_result = kg.search_multi(search_names, inp.country)

        if kg_result.has_matches:
            best = kg_result.best_match
            print(f"           ⚡ MATCH FOUND: {best.name} ({best.country})")
            print(f"              Labels: {best.risk_labels}")
            print(f"              Confidence: {best.confidence:.0%}")
            print(f"              Source: {kg_result.source}")
        else:
            print(f"           ✓ No matching entities found ({kg_result.source})")
        print()

        print(f"  Step 3 · Evaluating risk signals...")
        result = await engine.evaluate(inp, kg_result)
        for s in result.signals:
            sev_icon = {"critical": "🔴", "elevated": "🟡", "minor": "⚪"}[s.severity]
            print(f"           {sev_icon} [{s.code}] {s.description}")
        print()

        print(f"  Step 4 · Decision logic applied")
        emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[result.decision]
        print(f"           → {emoji} {result.decision} — {result.decision_label}")
        print()

        print(f"  Step 5 · Generating report...")
        print(result.to_report())
        print()


if __name__ == "__main__":
    import sys
    if sys.stdout and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(
        description="ClearCheck — Merchant Risk Triage Agent",
        epilog="Examples:\n"
               "  python server.py \"Check Parsian Bank in Iran\"\n"
               "  python server.py \"我们要接入一家迪拜的Golden Star Trading，20万美金的单子\"\n"
               "  python server.py --chat\n"
               "  python server.py --name \"Parsian Bank\" --country \"Iran\"\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="*", help="Natural language query (e.g. 'Check Parsian Bank in Iran')")
    parser.add_argument("--name", default="", help="Entity name (structured mode)")
    parser.add_argument("--country", default="", help="Country (structured mode)")
    parser.add_argument("--amount", type=float, default=0.0, help="Transaction amount in USD")
    parser.add_argument("--currency", default="", help="Payment currency")
    parser.add_argument("--goods", default="", help="Goods/service category")
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--port", type=int, default=8000, help="Server port (with --serve)")

    args = parser.parse_args()

    if args.serve:
        import uvicorn
        print("Starting ClearCheck server...")
        uvicorn.run("server:app", host="0.0.0.0", port=args.port, reload=True)
    elif args.chat:
        asyncio.run(run_chat())
    elif args.query:
        # Natural language mode — join all positional args
        query_text = " ".join(args.query)
        asyncio.run(run_triage(query_text=query_text))
    elif args.name:
        # Structured mode
        asyncio.run(run_triage(name=args.name, country=args.country,
                               amount=args.amount, currency=args.currency, goods=args.goods))
    else:
        parser.print_help()
