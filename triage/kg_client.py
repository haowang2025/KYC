"""
triage — ArangoDB Knowledge Graph Client

Queries the entity KG (DB: Sanction) for sanctions, PEP, and corporate data.
Falls back to built-in demo data if ArangoDB is unavailable.

Schema (ArangoDB collections):
  Documents:  entities, sanctions_entries, aliases, audit_logs, data_versions
  Edges:      entity_to_entry, ownership_edges, control_edges,
              director_edges, address_edges, bank_account_edges
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("triage.kg")


# ── Data Transfer Objects ─────────────────────────────────────────────────

@dataclass
class KGEntity:
    """A single entity returned from the knowledge graph."""
    key: str
    name: str
    entity_type: str = "organization"
    country: str = ""
    aliases: list[str] = field(default_factory=list)
    risk_labels: list[str] = field(default_factory=list)
    source_lists: list[str] = field(default_factory=list)
    identifiers: dict = field(default_factory=dict)
    last_updated: str = ""
    confidence: float = 0.0

    def is_sanctioned(self) -> bool:
        return bool(set(self.risk_labels) & {
            "SDN", "BLOCKED", "SANCTIONED", "EU_SANCTIONS",
            "UN_SANCTIONS", "OFSI", "sanction",
        })

    def is_pep(self) -> bool:
        return "PEP" in self.risk_labels

    def has_adverse_media(self) -> bool:
        return "ADVERSE_MEDIA" in self.risk_labels


@dataclass
class KGResult:
    """Result of a KG search."""
    query: str
    matches: list[KGEntity] = field(default_factory=list)
    related_entities: list[KGEntity] = field(default_factory=list)
    source: str = "arangodb"  # "arangodb" | "fallback"
    error: Optional[str] = None

    @property
    def best_match(self) -> Optional[KGEntity]:
        if not self.matches:
            return None
        return max(self.matches, key=lambda e: e.confidence)

    @property
    def has_matches(self) -> bool:
        return len(self.matches) > 0


# ── Fallback Demo Data ────────────────────────────────────────────────────

FALLBACK_ENTITIES: dict[str, KGEntity] = {
    "parsian bank": KGEntity(
        key="OFAC-12847", name="Parsian Bank",
        entity_type="organization", country="Iran",
        aliases=["Bank Parsian", "Parsian Bank (Iran)"],
        risk_labels=["SDN", "BLOCKED"],
        source_lists=["OFAC SDN", "EU Consolidated"],
        identifiers={"swift": "BKPAIRTHXXX"},
        last_updated="2026-03-15", confidence=0.96,
    ),
    "melli bank": KGEntity(
        key="OFAC-9121", name="Bank Melli Iran",
        entity_type="organization", country="Iran",
        aliases=["Melli Bank", "Bank Melli", "BMI"],
        risk_labels=["SDN", "BLOCKED"],
        source_lists=["OFAC SDN", "EU Consolidated", "UN Consolidated"],
        identifiers={"swift": "MEABORITHXXX"},
        last_updated="2026-03-15", confidence=0.98,
    ),
    "korea kwangson banking": KGEntity(
        key="OFAC-18231", name="Korea Kwangson Banking Corp",
        entity_type="organization", country="North Korea",
        aliases=["KKBC", "Kwangson Banking"],
        risk_labels=["SDN", "BLOCKED"],
        source_lists=["OFAC SDN", "UN Consolidated"],
        last_updated="2026-02-20", confidence=0.95,
    ),
    "golden star trading": KGEntity(
        key="WATCHLIST-44821", name="Golden Star Trading LLC",
        entity_type="organization", country="UAE",
        aliases=["Golden Star General Trading", "GS Trading FZE"],
        risk_labels=["ADVERSE_MEDIA"],
        source_lists=["Adverse Media DB"],
        identifiers={"trade_license": "DXB-882991"},
        last_updated="2026-01-10", confidence=0.67,
    ),
    "petro suisse": KGEntity(
        key="WATCHLIST-55102", name="Petro Suisse Intertrade SA",
        entity_type="organization", country="Switzerland",
        aliases=["Petro Suisse", "PSI Trading"],
        risk_labels=["PEP"],
        source_lists=["PEP Database"],
        identifiers={"uid": "CHE-112.233.445"},
        last_updated="2025-12-01", confidence=0.72,
    ),
}


# ── KG Client ─────────────────────────────────────────────────────────────

class KGClient:
    """
    Client for the Sanction entity knowledge graph.

    Tries ArangoDB first; on failure, falls back to hardcoded entities.

    ArangoDB schema:
      - entities:           main entity docs (name, country, entity_type, ...)
      - sanctions_entries:  sanctions list entries
      - aliases:            alias name documents
      - entity_to_entry:    edge linking entities → sanctions_entries
      - ownership_edges:    ownership relationships
      - control_edges:      control relationships
      - director_edges:     director relationships
      - address_edges:      address info
      - bank_account_edges: bank account relationships
    """

    def __init__(self):
        self._arango_db = None
        self._init_arango()

    @property
    def is_connected(self) -> bool:
        return self._arango_db is not None

    def _init_arango(self):
        """Connect to ArangoDB with a short timeout. Silently fall back on failure."""
        url = os.getenv("ARANGO_URL", "")
        db_name = os.getenv("ARANGO_DB", "Sanction")
        user = os.getenv("ARANGO_USER", "root")
        password = os.getenv("ARANGO_PASSWORD", "")

        if not url:
            logger.info("ARANGO_URL not set — using fallback data")
            return

        try:
            from arango import ArangoClient
            import requests

            # Use a short connection timeout to avoid long waits
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(max_retries=1)
            session.mount("http://", adapter)
            session.mount("https://", adapter)

            client = ArangoClient(
                hosts=url,
                request_timeout=10,
            )
            self._arango_db = client.db(
                db_name,
                username=user,
                password=password,
            )
            # Quick connectivity test
            self._arango_db.version()
            logger.info("Connected to ArangoDB [Production Cluster] / %s", db_name)
        except Exception as exc:
            logger.warning("ArangoDB unavailable (%s) — using fallback data", exc)
            self._arango_db = None

    # ── Public API ────────────────────────────────────────────────────

    def search(self, name: str, country: str = "") -> KGResult:
        """
        Search the KG for an entity. Strategy:
        1. Try ArangoDB (fast, simple query)
        2. Merge with fallback data (ensures demo always has results)
        """
        arango_result = None
        if self._arango_db:
            arango_result = self._search_arango(name, country)

        fallback_result = self._search_fallback(name, country)

        # Merge: ArangoDB results take priority, then fallback
        if arango_result and arango_result.has_matches:
            return arango_result
        if arango_result and not arango_result.error:
            # ArangoDB responded but no matches — still note the source
            if fallback_result.has_matches:
                fallback_result.source = "arangodb+fallback"
                return fallback_result
            return arango_result  # truly no match anywhere
        return fallback_result

    def search_multi(self, names: list[str], country: str = "") -> KGResult:
        """
        Search the KG using multiple name variants (canonical + aliases).
        LLM normalization produces these variants.
        Returns the best result across all searches.
        """
        all_matches: list[KGEntity] = []
        source = "fallback"
        seen_keys: set[str] = set()

        for name in names:
            result = self.search(name, country)
            if "arangodb" in result.source:
                source = result.source
            for m in result.matches:
                key = m.key or m.name.lower()
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_matches.append(m)

        return KGResult(
            query=names[0] if names else "",
            matches=all_matches,
            source=source,
        )

    # ── ArangoDB Queries ──────────────────────────────────────────────

    def _search_arango(self, name: str, country: str) -> KGResult:
        """
        Fast query on the real ArangoDB Sanction database.
        Simple name search on entities collection + sanctions entry lookup.
        """
        try:
            # Simple, fast query — no edge traversals to keep latency low
            aql = """
            FOR e IN entities
                FILTER CONTAINS(LOWER(e.name), LOWER(@name))
                    OR LOWER(e.name) == LOWER(@name)
                LIMIT 10
                LET sanctions = (
                    FOR se IN 1..1 OUTBOUND e._id entity_to_entry
                        RETURN se
                )
                RETURN MERGE(e, {sanctions: sanctions})
            """
            cursor = self._arango_db.aql.execute(
                aql, bind_vars={"name": name}, ttl=15
            )

            matches = []
            for doc in cursor:
                risk_labels = doc.get("risk_labels") or []
                source_lists = doc.get("source_lists") or []

                # Mark as sanctioned if linked to sanctions_entries
                sanctions = doc.get("sanctions", [])
                if sanctions:
                    for se in sanctions:
                        sl = se.get("source_list") or se.get("list_name") or "sanctions list"
                        if sl not in source_lists:
                            source_lists.append(sl)
                        if "SANCTIONED" not in risk_labels:
                            risk_labels.append("SANCTIONED")

                entity = KGEntity(
                    key=doc.get("_key", ""),
                    name=doc.get("name", ""),
                    entity_type=doc.get("entity_type", "organization"),
                    country=doc.get("country", ""),
                    aliases=doc.get("aliases") or [],
                    risk_labels=risk_labels,
                    source_lists=source_lists,
                    identifiers=doc.get("identifiers") or {},
                    last_updated=doc.get("last_updated", ""),
                    confidence=0.85 if doc.get("name", "").lower() != name.lower() else 0.95,
                )

                if country and entity.country and entity.country.lower() == country.lower():
                    entity.confidence = min(entity.confidence + 0.05, 1.0)

                matches.append(entity)

            return KGResult(query=name, matches=matches, source="arangodb")

        except Exception as exc:
            logger.warning("ArangoDB query failed (%s) — falling back", exc)
            return KGResult(query=name, source="fallback", error=str(exc))

    # ── Fallback ──────────────────────────────────────────────────────

    def _search_fallback(self, name: str, country: str) -> KGResult:
        """Search hardcoded entities with simple substring matching."""
        name_lower = name.lower().strip()
        matches: list[KGEntity] = []

        for key, entity in FALLBACK_ENTITIES.items():
            if key in name_lower or name_lower in key:
                matches.append(entity)
                continue
            for alias in entity.aliases:
                if name_lower in alias.lower() or alias.lower() in name_lower:
                    matches.append(entity)
                    break

        if country:
            for m in matches:
                if m.country.lower() == country.lower():
                    m.confidence = min(m.confidence + 0.1, 1.0)

        return KGResult(query=name, matches=matches, source="fallback")
