"""
ClearCheck — AgentHansa Expert Loop

Long-poll worker that receives merchant screening tasks from the AgentHansa
Task Mesh and returns triage results.

Usage:
    python expert_loop.py

Requires AGENTHANSA_API_KEY in .env
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

from kg_client import KGClient
from triage_engine import TriageEngine, TriageInput

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-20s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("clearcheck.expert")

API = "https://www.agenthansa.com"
AGENT_KEY = os.getenv("AGENTHANSA_API_KEY", "")


async def process_message(body: str, kg: KGClient, engine: TriageEngine) -> str:
    """Parse an incoming task message and return triage report."""
    try:
        # Try to parse as JSON task spec
        spec = json.loads(body) if body.strip().startswith("{") else None
    except json.JSONDecodeError:
        spec = None

    if spec:
        inp = TriageInput(
            entity_name=spec.get("entity_name", ""),
            country=spec.get("country", ""),
            entity_type=spec.get("entity_type", "merchant"),
            payment_currency=spec.get("payment_currency", ""),
            goods_category=spec.get("goods_category", ""),
            transaction_amount=spec.get("transaction_amount", 0.0),
        )
    else:
        # Free-form text — extract what we can
        inp = TriageInput(entity_name=body.strip(), country="Unknown")

    kg_result = kg.search(inp.entity_name, inp.country)
    result = await engine.evaluate(inp, kg_result)

    return result.to_report()


async def main():
    if not AGENT_KEY:
        print("ERROR: Set AGENTHANSA_API_KEY in .env to run the expert loop")
        sys.exit(1)

    kg = KGClient()
    engine = TriageEngine()
    cursor = 0

    logger.info("ClearCheck Expert Loop started — listening for tasks...")

    async with httpx.AsyncClient(timeout=70) as http:
        while True:
            try:
                r = await http.get(
                    f"{API}/api/experts/updates",
                    params={"offset": cursor, "wait": 60},
                    headers={"Authorization": f"Bearer {AGENT_KEY}"},
                )

                if r.status_code == 401:
                    logger.error("Invalid API key — check AGENTHANSA_API_KEY")
                    break

                data = r.json()

                for msg in data.get("messages", []):
                    logger.info("Received task: %s", msg.get("engagement_id"))
                    reply = await process_message(msg.get("body", ""), kg, engine)

                    await http.post(
                        f"{API}/api/engagements/{msg['engagement_id']}/messages",
                        headers={
                            "Authorization": f"Bearer {AGENT_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={"body": reply},
                    )
                    logger.info("Sent triage report for engagement %s", msg["engagement_id"])

                cursor = data.get("cursor", cursor)

            except httpx.TimeoutException:
                continue  # Normal — long poll timed out, retry
            except Exception as exc:
                logger.error("Error in expert loop: %s", exc)
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
