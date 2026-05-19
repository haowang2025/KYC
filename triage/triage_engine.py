"""
triage — Risk Triage Engine

Three-layer rule-based risk evaluation + LLM reasoning via TokenRouter.
"""

from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from .kg_client import KGResult, KGEntity

logger = logging.getLogger("triage.engine")

# ── FATF Reference Lists ──────────────────────────────────────────────────

FATF_BLACKLIST = {
    "north korea", "dprk", "democratic people's republic of korea",
    "iran", "myanmar",
}

FATF_GREYLIST = {
    "albania", "barbados", "burkina faso", "cameroon", "cayman islands",
    "croatia", "democratic republic of congo", "gibraltar", "haiti",
    "jamaica", "jordan", "mali", "mozambique", "nigeria", "panama",
    "philippines", "senegal", "south africa", "south sudan", "syria",
    "tanzania", "türkiye", "turkey", "uganda",
    "united arab emirates", "uae",
    "venezuela", "vietnam", "yemen",
}


# ── Data Structures ───────────────────────────────────────────────────────

@dataclass
class Signal:
    """A single risk signal detected during evaluation."""
    code: str               # e.g. "SANCTIONS_MATCH"
    severity: str           # "critical" | "elevated" | "minor"
    description: str        # human-readable explanation


@dataclass
class TriageInput:
    """Normalized input to the triage engine."""
    entity_name: str
    country: str
    entity_type: str = "merchant"
    address: str = ""
    registration_id: str = ""
    payment_currency: str = ""
    goods_category: str = ""
    transaction_amount: float = 0.0
    counterparty: str = ""


@dataclass
class TriageResult:
    """Complete triage output."""
    entity_name: str
    country: str
    decision: str           # "GREEN" | "YELLOW" | "RED"
    decision_label: str     # "PROCEED" | "REVIEW" | "HOLD"
    confidence: str         # "High" | "Medium" | "Low"
    reasons: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    timestamp: str = ""
    kg_source: str = ""     # "arangodb" | "fallback"

    def to_report(self) -> str:
        """Format as the structured text report for display."""
        emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}[self.decision]

        signals_str = ""
        for s in self.signals:
            sev = {"critical": "🔴", "elevated": "🟡", "minor": "⚪"}[s.severity]
            signals_str += f"    {sev} [{s.code}]: {s.description}\n"

        sources_str = "\n".join(f"    - {s}" for s in self.evidence_sources)
        limits_str = "\n".join(f"    - {l}" for l in self.limitations)
        reasons_str = "\n".join(f"    {i+1}. {r}" for i, r in enumerate(self.reasons[:3]))
        actions_str = "\n".join(f"    {i+1}. {a}" for i, a in enumerate(self.next_actions[:3]))

        return f"""
  ═══════════════════════════════════════════════════
    TRIAGE RISK TRIAGE REPORT
  ═══════════════════════════════════════════════════

    Entity:       {self.entity_name}
    Country:      {self.country}
    Checked:      {self.timestamp}

  ─────────────────────────────────────────────────
    DECISION:     {emoji}  {self.decision} — {self.decision_label}
  ─────────────────────────────────────────────────

    CONFIDENCE:   {self.confidence}

  ═══════════════════════════════════════════════════
    WHY — TOP 3 REASONS
  ═══════════════════════════════════════════════════

{reasons_str}

  ═══════════════════════════════════════════════════
    WHAT TO DO NEXT — 3 ACTIONS
  ═══════════════════════════════════════════════════

{actions_str}

  ═══════════════════════════════════════════════════
    EVIDENCE SUMMARY
  ═══════════════════════════════════════════════════

    Sources checked:
{sources_str}

    Signals triggered:
{signals_str}
    Limitations:
{limits_str}

  ═══════════════════════════════════════════════════
    This is a risk triage, not legal advice.
    Final decisions should involve human review.
  ═══════════════════════════════════════════════════
"""

    def to_dict(self) -> dict:
        """JSON-serializable dict for API responses."""
        return {
            "entity_name": self.entity_name,
            "country": self.country,
            "decision": self.decision,
            "decision_label": self.decision_label,
            "confidence": self.confidence,
            "reasons": self.reasons[:3],
            "next_actions": self.next_actions[:3],
            "signals": [{"code": s.code, "severity": s.severity, "description": s.description} for s in self.signals],
            "evidence_sources": self.evidence_sources,
            "limitations": self.limitations,
            "timestamp": self.timestamp,
            "kg_source": self.kg_source,
        }


@dataclass
class NormalizedEntity:
    """LLM-normalized entity for KG search."""
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "organization"
    country_normalized: str = ""
    transaction_amount: float = 0.0
    payment_currency: str = ""
    goods_category: str = ""
    notes: str = ""


# ── Triage Engine ─────────────────────────────────────────────────────────

class TriageEngine:
    """
    Three-layer risk evaluation + LLM reasoning.

    Layer A: Entity Risk (sanctions, PEP, adverse media)
    Layer B: Jurisdiction & Transaction Risk (FATF, currency, goods)
    Layer C: Data Completeness Risk (missing fields, ambiguity)
    """

    def __init__(self):
        self._tokenrouter_key = os.getenv("TOKENROUTER_API_KEY", "")
        self._tokenrouter_url = os.getenv("TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1")
        self._model = os.getenv("TOKENROUTER_MODEL", "claude-sonnet-4-20250514")

    # ── Step 1: Parse & Normalize via LLM ────────────────────────────

    async def parse_query(self, text: str, name: str = "", country: str = "") -> NormalizedEntity:
        """
        Use LLM to parse a natural language query OR normalize structured input.

        Handles both:
          - Free text: "我们要接入一家叫 Parsian Bank 的伊朗供应商，20 万美金的订单"
          - Structured: name="Parsian Bank", country="Iran"
        """
        if not self._tokenrouter_key:
            return NormalizedEntity(
                canonical_name=name or text.strip(),
                aliases=[name or text.strip()],
                country_normalized=country,
            )

        if text and not name:
            # Free-text mode — extract everything from natural language
            prompt = f"""You are a compliance entity resolution assistant. A user has submitted a natural language
query about an entity they want to screen for risk. Extract the structured fields and normalize
the entity for sanctions screening / knowledge graph lookup.

User query: {text}

Respond in this exact JSON format, no other text:
{{
  "canonical_name": "The standard English name of the entity being checked",
  "aliases": ["alias1", "alias2", "alias3"],
  "entity_type": "organization or individual",
  "country_normalized": "Full English country name (e.g. 'Iran' not 'IR', 'United Arab Emirates' not 'UAE')",
  "transaction_amount": 0,
  "payment_currency": "",
  "goods_category": "",
  "notes": "Brief note on any ambiguity, transliterations, or context from the query"
}}

Rules:
- Extract the entity name even if embedded in a sentence
- Infer country from context clues (language, currency, city names) if not explicit
- Generate aliases: transliterations, legal suffix variants, DBA names, common abbreviations
- If the user mentions an amount, extract it as transaction_amount (in USD)
- If no entity can be identified, set canonical_name to the full query text
- Max 5 aliases"""
        else:
            # Structured mode — just normalize the given name + country
            prompt = f"""You are a compliance entity resolution assistant. Given a raw entity name and country,
produce a normalized version for sanctions screening / knowledge graph lookup.

Raw entity name: {name}
Raw country: {country}

Respond in this exact JSON format, no other text:
{{
  "canonical_name": "The standard English name used in sanctions lists and corporate registries",
  "aliases": ["alias1", "alias2", "alias3"],
  "entity_type": "organization or individual",
  "country_normalized": "Full English country name (e.g. 'Iran' not 'IR', 'United Arab Emirates' not 'UAE')",
  "transaction_amount": 0,
  "payment_currency": "",
  "goods_category": "",
  "notes": "Brief note on any name ambiguity or transliteration issues"
}}

Rules for aliases:
- Include the original raw name if different from canonical
- Include common transliterations (e.g. Arabic/Farsi/Chinese romanizations)
- Include known DBA (doing-business-as) names
- Include name with and without legal suffixes (LLC, Ltd, Corp, etc.)
- Max 5 aliases"""

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"{self._tokenrouter_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._tokenrouter_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 400,
                        "temperature": 0.1,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()

                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = json.loads(content)

                return NormalizedEntity(
                    canonical_name=parsed.get("canonical_name", name or text),
                    aliases=parsed.get("aliases", [name or text]),
                    entity_type=parsed.get("entity_type", "organization"),
                    country_normalized=parsed.get("country_normalized", country),
                    transaction_amount=parsed.get("transaction_amount", 0),
                    payment_currency=parsed.get("payment_currency", ""),
                    goods_category=parsed.get("goods_category", ""),
                    notes=parsed.get("notes", ""),
                )

        except Exception as exc:
            logger.warning("LLM parse failed (%s) — using raw input", exc)
            return NormalizedEntity(
                canonical_name=name or text.strip(),
                aliases=[name or text.strip()],
                country_normalized=country,
            )

    async def evaluate(self, inp: TriageInput, kg_result: KGResult) -> TriageResult:
        """Run the full triage pipeline."""
        signals: list[Signal] = []

        # ── Layer A: Entity Risk ──────────────────────────────────────
        best = kg_result.best_match
        if best:
            if best.is_sanctioned() and best.confidence >= 0.80:
                ls = ", ".join(best.source_lists) or "sanctions list"
                signals.append(Signal(
                    "SANCTIONS_MATCH", "critical",
                    f"Entity matches designated entry on {ls} — confidence {best.confidence:.0%}"
                ))
            elif best.is_sanctioned() and best.confidence >= 0.50:
                signals.append(Signal(
                    "PARTIAL_MATCH", "elevated",
                    f"Possible sanctions match — confidence {best.confidence:.0%}"
                ))
            if best.is_pep():
                signals.append(Signal(
                    "PEP_FLAG", "elevated",
                    "Entity or related person flagged as Politically Exposed Person"
                ))
            if best.has_adverse_media():
                signals.append(Signal(
                    "ADVERSE_MEDIA", "elevated",
                    "Significant negative media coverage found"
                ))
        else:
            signals.append(Signal(
                "NO_MATCH", "minor",
                "No matching entity found in knowledge graph"
            ))

        # ── Layer B: Jurisdiction & Transaction Risk ──────────────────
        country_lower = inp.country.lower().strip()

        if country_lower in FATF_BLACKLIST:
            signals.append(Signal(
                "FATF_BLACKLIST", "critical",
                f"Country '{inp.country}' is on FATF high-risk (blacklist)"
            ))
        elif country_lower in FATF_GREYLIST:
            signals.append(Signal(
                "FATF_GREYLIST", "elevated",
                f"Country '{inp.country}' is under FATF increased monitoring (grey list)"
            ))

        sensitive_goods = {"arms", "weapons", "nuclear", "oil", "petroleum",
                          "military", "dual-use", "explosives"}
        if inp.goods_category and any(g in inp.goods_category.lower() for g in sensitive_goods):
            signals.append(Signal(
                "SENSITIVE_GOODS", "elevated",
                f"Goods category '{inp.goods_category}' flagged as sensitive"
            ))

        if inp.transaction_amount > 100_000:
            elevated_present = any(s.severity in ("critical", "elevated") for s in signals)
            if elevated_present:
                signals.append(Signal(
                    "HIGH_VALUE", "elevated",
                    f"Transaction amount ${inp.transaction_amount:,.0f} is high-value with other risk signals present"
                ))

        # ── Layer C: Data Completeness Risk ───────────────────────────
        if not inp.country:
            signals.append(Signal("MISSING_COUNTRY", "elevated", "No country provided"))
        if not inp.registration_id:
            signals.append(Signal("MISSING_ID", "minor", "No registration / identification number provided"))
        if kg_result.has_matches and len(kg_result.matches) > 1:
            signals.append(Signal(
                "AMBIGUOUS_ENTITY", "elevated",
                f"Multiple candidate entities found ({len(kg_result.matches)} matches) — disambiguation uncertain"
            ))

        # ── Decision Logic ────────────────────────────────────────────
        critical_count = sum(1 for s in signals if s.severity == "critical")
        elevated_count = sum(1 for s in signals if s.severity == "elevated")
        minor_count = sum(1 for s in signals if s.severity == "minor")

        if critical_count > 0:
            decision, label = "RED", "HOLD"
            confidence = "High" if critical_count >= 2 else "Medium"
        elif elevated_count >= 2:
            decision, label = "YELLOW", "REVIEW"
            confidence = "Medium"
        elif elevated_count == 1:
            decision, label = "YELLOW", "REVIEW"
            confidence = "Medium"
        elif minor_count >= 3:
            decision, label = "YELLOW", "REVIEW"
            confidence = "Low"
        else:
            decision, label = "GREEN", "PROCEED"
            confidence = "High" if not minor_count else "Medium"

        # ── Build evidence ────────────────────────────────────────────
        evidence_sources = []
        if kg_result.source == "arangodb":
            evidence_sources.append(f"Entity Knowledge Graph (ArangoDB) — {'match found' if kg_result.has_matches else 'no match'}")
        else:
            evidence_sources.append(f"Fallback entity data — {'match found' if kg_result.has_matches else 'no match'}")
        evidence_sources.append(f"FATF country lists — {inp.country} status checked")
        if inp.goods_category:
            evidence_sources.append(f"Goods category screening — '{inp.goods_category}' checked")

        limitations = ["Ownership / UBO parsing not yet automated",
                       "This is a risk triage, not a legal opinion"]
        if kg_result.source == "fallback":
            limitations.insert(0, "ArangoDB unavailable — using demo fallback data")

        # ── LLM-generated reasons and actions ─────────────────────────
        reasons, actions = await self._llm_reasoning(inp, signals, decision, best)

        return TriageResult(
            entity_name=inp.entity_name,
            country=inp.country,
            decision=decision,
            decision_label=label,
            confidence=confidence,
            reasons=reasons,
            next_actions=actions,
            signals=signals,
            evidence_sources=evidence_sources,
            limitations=limitations,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            kg_source=kg_result.source,
        )

    # ── LLM Reasoning ─────────────────────────────────────────────────

    async def _llm_reasoning(
        self,
        inp: TriageInput,
        signals: list[Signal],
        decision: str,
        best_match: Optional[KGEntity],
    ) -> tuple[list[str], list[str]]:
        """Use TokenRouter LLM to generate human-readable reasons and actions."""

        if not self._tokenrouter_key:
            return self._fallback_reasoning(signals, decision)

        signal_desc = "\n".join(f"- [{s.code}] ({s.severity}): {s.description}" for s in signals)
        match_info = ""
        if best_match:
            match_info = f"Best KG match: {best_match.name} ({best_match.country}), labels: {best_match.risk_labels}, confidence: {best_match.confidence:.0%}"

        prompt = f"""You are a risk analyst assistant. Based on the following risk signals for a merchant triage,
generate exactly 3 concise reasons for the {decision} decision, and exactly 3 specific next actions.

Entity: {inp.entity_name}
Country: {inp.country}
Decision: {decision}
{match_info}

Risk signals detected:
{signal_desc}

Respond in this exact JSON format, no other text:
{{"reasons": ["reason1", "reason2", "reason3"], "actions": ["action1", "action2", "action3"]}}

Rules:
- Each reason must cite a specific signal or evidence
- Each action must be operationally specific (not vague like "be careful")
- Use professional risk ops language
- Never say "the entity IS sanctioned" — say "matches a designated entry"
- Never give legal advice"""

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{self._tokenrouter_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._tokenrouter_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]

                # Parse JSON from response (handle markdown fences)
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                parsed = json.loads(content)
                return parsed.get("reasons", [])[:3], parsed.get("actions", [])[:3]

        except Exception as exc:
            logger.warning("LLM reasoning failed (%s) — using rule-based fallback", exc)
            return self._fallback_reasoning(signals, decision)

    def _fallback_reasoning(
        self, signals: list[Signal], decision: str
    ) -> tuple[list[str], list[str]]:
        """Generate reasons/actions from signals without LLM."""

        reasons = [s.description for s in signals if s.severity in ("critical", "elevated")]
        if not reasons:
            reasons = [s.description for s in signals]
        reasons = reasons[:3]
        while len(reasons) < 3:
            reasons.append("No additional risk indicators detected")

        if decision == "RED":
            actions = [
                "Do not proceed with onboarding or transaction",
                "Escalate to compliance team for full review",
                "Document findings and retain for audit trail",
            ]
        elif decision == "YELLOW":
            actions = [
                "Request additional documentation from the entity",
                "Perform enhanced due diligence before proceeding",
                "Flag for senior analyst review within 24 hours",
            ]
        else:
            actions = [
                "Proceed with standard onboarding workflow",
                "Schedule periodic re-screening per policy",
                "Log triage result for audit records",
            ]

        return reasons, actions
