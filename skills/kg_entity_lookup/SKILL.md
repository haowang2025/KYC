---
name: kg_entity_lookup
description: Query the entity knowledge graph (ArangoDB) for sanctions, PEP, and corporate entity data.
---

# Entity Knowledge Graph Lookup Skill

You have access to an entity knowledge graph stored in ArangoDB. Use this skill when you need to check if a merchant, supplier, or counterparty has risk-relevant records.

## Available Queries

### 1. Entity Search by Name

```aql
FOR doc IN entities
  FILTER LOWER(doc.name) == LOWER(@name)
     OR @name IN doc.aliases
  RETURN {
    id: doc._key,
    name: doc.name,
    aliases: doc.aliases,
    entity_type: doc.entity_type,
    country: doc.country,
    risk_labels: doc.risk_labels,
    source_lists: doc.source_lists,
    identifiers: doc.identifiers,
    last_updated: doc.last_updated
  }
```

### 2. Entity Search by Name + Country

```aql
FOR doc IN entities
  FILTER (LOWER(doc.name) == LOWER(@name) OR @name IN doc.aliases)
     AND doc.country == @country
  RETURN doc
```

### 3. Fuzzy Name Search (if full-text index available)

```aql
FOR doc IN FULLTEXT(entities, "name", @search_term)
  RETURN {
    id: doc._key,
    name: doc.name,
    aliases: doc.aliases,
    country: doc.country,
    risk_labels: doc.risk_labels,
    score: BM25(doc)
  }
```

### 4. Relationship Traversal

```aql
FOR v, e, p IN 1..2 OUTBOUND @entity_id GRAPH 'entity_graph'
  RETURN {
    related_entity: v.name,
    relationship: e.type,
    country: v.country,
    risk_labels: v.risk_labels
  }
```

## How to Use

When the main `merchant_risk_triage` skill asks you to search the KG:

1. First try **exact match** (Query 1)
2. If no results, try **fuzzy search** (Query 3)
3. If you get results, check for **related entities** (Query 4)
4. Return all findings to the triage reasoning step

## Interpreting Results

| Field | Meaning |
|-------|---------|
| `risk_labels` | Array of labels like `["SDN", "BLOCKED"]`, `["PEP"]`, `["ADVERSE_MEDIA"]` |
| `source_lists` | Which sanctions/watchlists the entity appears on |
| `aliases` | Known alternative names, transliterations, DBAs |
| `identifiers` | Registration numbers, tax IDs, vessel IMOs, etc. |
| `entity_type` | individual, organization, vessel, aircraft |

## If ArangoDB Is Not Connected

Fall back to these alternative approaches:
1. Use web search to check OpenSanctions (opensanctions.org)
2. Search OFAC's SDN list (sanctionssearch.ofac.treas.gov)
3. Check the entity name against the FATF high-risk jurisdictions list (hardcoded in main skill)
4. Clearly note in the output: "KG unavailable — web search used as fallback"
