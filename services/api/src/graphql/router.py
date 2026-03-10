"""FastAPI router that mounts the Strawberry GraphQL endpoint.

Endpoint: POST /api/v1/graphql  — execute queries
GraphiQL:  GET  /api/v1/graphql  — browser IDE (DEBUG mode only)

Authentication is enforced by the existing AuthMiddleware.
"""

from fastapi import Request
from strawberry.fastapi import GraphQLRouter

from src.config import settings
from src.graphql.schema import schema

_POST_DESCRIPTION = """\
Execute a GraphQL query against silver and gold entities.

**Request body** (`application/json`):
```json
{
  "query": "{ entities { name layer fields { name dataType isPii } } }",
  "variables": {}
}
```

**Available queries:**

`entities(layer: String): [CatalogueEntity]`
> List silver and gold entities visible to the caller.
> Optionally filter by `layer: "silver"` or `layer: "gold"`.

`entityData(name: String!, layer: String!, limit: Int = 100): EntityData`
> Fetch up to `limit` rows (max 500) from a silver or gold entity.
> Results are Redis-cached for 10 minutes; `cached: true` means the response was served from cache.
> Each item in `rows` is a JSON-encoded object string.

**Example — fetch orders:**
```json
{
  "query": "{ entityData(name: \\"orders\\", layer: \\"silver\\") { columns rows count cached } }"
}
```

**RBAC:** viewers see gold only; all other roles see silver + gold.
PII fields are masked for analyst/viewer/engineer roles.
"""

_GET_DESCRIPTION = "GraphiQL browser IDE — only available when `DEBUG=true`."


async def _get_context(request: Request) -> dict:
    return {"request": request}


router = GraphQLRouter(
    schema,
    context_getter=_get_context,
    graphql_ide="graphiql" if settings.debug else None,
)

# Patch Strawberry's auto-generated route metadata with useful docs
for _route in router.routes:
    if not hasattr(_route, "methods"):
        continue
    if "POST" in _route.methods:  # type: ignore[union-attr]
        _route.summary = "Execute GraphQL Query"  # type: ignore[attr-defined]
        _route.description = _POST_DESCRIPTION  # type: ignore[attr-defined]
    elif "GET" in _route.methods:  # type: ignore[union-attr]
        _route.summary = "GraphiQL IDE"  # type: ignore[attr-defined]
        _route.description = _GET_DESCRIPTION  # type: ignore[attr-defined]
