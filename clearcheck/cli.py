from __future__ import annotations

import argparse
import asyncio
import sys

from .api import engine, kg
from .triage_engine import TriageInput


async def run_triage(
    query_text: str = "",
    name: str = "",
    country: str = "",
    amount: float = 0.0,
    currency: str = "",
    goods: str = "",
):
    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║           C L E A R C H E C K             ║")
    print("  ║     Merchant Risk Triage Agent            ║")
    print("  ╚═══════════════════════════════════════════╝")
    print()

    print("  Step 1 · Parsing query via LLM...")
    if query_text:
        print(f'           Input:      "{query_text}"')
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

    print("  Step 2 · Searching knowledge graph...")
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

    print("  Step 3 · Evaluating risk signals...")
    result = await engine.evaluate(inp, kg_result)
    for s in result.signals:
        sev_icon = {"critical": "🔴", "elevated": "🟡", "minor": "⚪"}[s.severity]
        print(f"           {sev_icon} [{s.code}] {s.description}")
    print()

    print("  Step 4 · Decision logic applied")
    emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[result.decision]
    print(f"           → {emoji} {result.decision} — {result.decision_label}")
    print()

    print("  Step 5 · Generating report...")
    print(result.to_report())


async def run_chat():
    print()
    print("  ╔═══════════════════════════════════════════╗")
    print("  ║           C L E A R C H E C K             ║")
    print("  ║     Merchant Risk Triage Agent            ║")
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
        print("  Step 1 · Parsing query via LLM...")
        print(f'           Input:      "{query}"')
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

        print("  Step 2 · Searching knowledge graph...")
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

        print("  Step 3 · Evaluating risk signals...")
        result = await engine.evaluate(inp, kg_result)
        for s in result.signals:
            sev_icon = {"critical": "🔴", "elevated": "🟡", "minor": "⚪"}[s.severity]
            print(f"           {sev_icon} [{s.code}] {s.description}")
        print()

        print("  Step 4 · Decision logic applied")
        emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[result.decision]
        print(f"           → {emoji} {result.decision} — {result.decision_label}")
        print()

        print("  Step 5 · Generating report...")
        print(result.to_report())
        print()


def main(argv: list[str] | None = None):
    if sys.stdout and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(
        description="ClearCheck — Merchant Risk Triage Agent",
        epilog="Examples:\n"
        '  python -m clearcheck "Check Parsian Bank in Iran"\n'
        '  python -m clearcheck "我们要接入一家迪拜的Golden Star Trading，20万美金的单子"\n'
        "  python -m clearcheck --chat\n"
        '  python -m clearcheck --name "Parsian Bank" --country "Iran"\n'
        "  python -m clearcheck --serve --port 8000\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="*", help="Natural language query")
    parser.add_argument("--name", default="", help="Entity name (structured mode)")
    parser.add_argument("--country", default="", help="Country (structured mode)")
    parser.add_argument("--amount", type=float, default=0.0, help="Transaction amount in USD")
    parser.add_argument("--currency", default="", help="Payment currency")
    parser.add_argument("--goods", default="", help="Goods/service category")
    parser.add_argument("--chat", action="store_true", help="Interactive chat mode")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI server")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (with --serve)")
    parser.add_argument("--port", type=int, default=8000, help="Server port (with --serve)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload (dev only)")

    args = parser.parse_args(argv)

    if args.serve:
        import uvicorn

        uvicorn.run(
            "clearcheck.api:app",
            host=args.host,
            port=args.port,
            reload=bool(args.reload),
        )
        return

    if args.chat:
        asyncio.run(run_chat())
        return

    if args.query:
        query_text = " ".join(args.query)
        asyncio.run(run_triage(query_text=query_text))
        return

    if args.name:
        asyncio.run(
            run_triage(
                name=args.name,
                country=args.country,
                amount=args.amount,
                currency=args.currency,
                goods=args.goods,
            )
        )
        return

    parser.print_help()

