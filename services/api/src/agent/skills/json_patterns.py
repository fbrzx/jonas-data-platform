"""DuckDB JSON flattening skill library — few-shot patterns for the agent system prompt.

Injected into the system prompt when bronze entities with webhook/JSON payload storage are present.
"""

JSON_SKILLS_PROMPT = """\
## DuckDB JSON patterns — use these exact patterns, never Postgres equivalents

### Extract flat scalar fields from payload
```sql
SELECT
    json_extract_string(payload, '$.id')                        AS id,
    CAST(json_extract(payload, '$.amount') AS DOUBLE)           AS amount,
    CAST(json_extract_string(payload, '$.created_at') AS TIMESTAMP) AS created_at,
    CAST(json_extract(payload, '$.is_active') AS BOOLEAN)       AS is_active
FROM bronze.{source}
WHERE json_extract_string(payload, '$.id') IS NOT NULL
```

### Flatten a JSON array into rows (one row per array element)
```sql
SELECT
    json_extract_string(payload, '$.parent_id')                 AS parent_id,
    json_extract_string(elem, '$.item_id')                      AS item_id,
    CAST(json_extract(elem, '$.quantity') AS INTEGER)           AS quantity
FROM bronze.{source}
CROSS JOIN UNNEST(json_extract(payload, '$.items')::JSON[]) AS t(elem)
WHERE json_extract(payload, '$.items') IS NOT NULL
```
⚠️ The `::JSON[]` cast is REQUIRED. Never use CROSS JOIN LATERAL, json_array_elements, or json_each.

### Re-aggregate flat rows back into a JSON array (for gold views)
```sql
SELECT
    parent_id,
    to_json(list({'item_id': item_id, 'quantity': quantity})) AS items_json
FROM silver.{source}
GROUP BY parent_id
```

"""
