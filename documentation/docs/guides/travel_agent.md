# Travel Agent (MCP)

Voyage includes a **Travel Agent** interface exposed through an **MCP-compatible HTTP endpoint**. This lets external MCP clients read and manage trip itineraries programmatically for authenticated users.

## Endpoint

- Default path: `api/mcp`
- Configurable with: `DJANGO_MCP_ENDPOINT`

If you run Voyage at `https://voyage.example.com`, the default MCP URL is:

```text
https://voyage.example.com/api/mcp
```

## Authentication

MCP requests must include a DRF token in the `Authorization` header:

```text
Authorization: Token <token>
```

Use a token associated with the Voyage user account that should execute the MCP actions.

### Get a token from an authenticated session

Voyage exposes a token bootstrap endpoint for logged-in users:

- `GET /auth/mcp-token/`

Call it with your authenticated browser session (or any authenticated session cookie flow). It returns:

```json
{ "token": "<token>" }
```

Then use that token in all MCP requests with the same header format:

```text
Authorization: Token <token>
```

## Available MCP tools

The Voyage MCP server currently exposes these tools:

- `list_collections`
- `get_collection_details`
- `list_itinerary_items`
- `create_itinerary_item`
- `reorder_itinerary`

### Tool parameters

#### `list_collections`

- No parameters.

#### `get_collection_details`

- `collection_id` (required, string UUID): collection to inspect.

#### `list_itinerary_items`

- `collection_id` (optional, string UUID): if provided, limits results to one collection.

#### `create_itinerary_item`

Required:

- `collection_id` (string UUID)
- `content_type` (`location` \| `transportation` \| `note` \| `lodging` \| `visit` \| `checklist`)
- `object_id` (string UUID, id of the referenced content object)

Optional:

- `date` (ISO date string, required when `is_global` is `false`)
- `is_global` (boolean, default `false`; when `true`, `date` must be omitted)
- `order` (integer; if omitted, Voyage appends to the end of the relevant scope)

#### `reorder_itinerary`

Required:

- `items` (list of item update objects)

Each entry in `items` should include:

- `id` (required, string UUID of `CollectionItineraryItem`)
- `date` (ISO date string for dated items)
- `order` (integer target order)
- `is_global` (optional boolean; include when moving between global and dated scopes)

## End-to-end example flow

This example shows a typical interaction from an MCP client.

1. **Connect** to the MCP endpoint using your Voyage server URL and token header.
2. Call **`list_collections`** to find the trip/collection you want to work with.
3. Call **`get_collection_details`** for the selected collection ID to inspect current trip context.
4. Call **`list_itinerary_items`** for a specific date or collection scope.
5. Call **`create_itinerary_item`** to add a new stop (for example, a location or note) to the itinerary.
6. Call **`reorder_itinerary`** to persist the final ordering after insertion.

### Example request headers (HTTP transport)

```http
POST /api/mcp HTTP/1.1
Host: voyage.example.com
Authorization: Token <token>
Content-Type: application/json
```

### Example interaction sequence (conceptual)

```text
Client -> list_collections
Server -> [{"id": "6c5d9f61-2f09-4882-b277-8884b633d36b", "name": "Japan 2026"}, ...]

Client -> get_collection_details({"collection_id": "6c5d9f61-2f09-4882-b277-8884b633d36b"})
Server -> {...collection metadata...}

Client -> list_itinerary_items({"collection_id": "6c5d9f61-2f09-4882-b277-8884b633d36b"})
Server -> [...current ordered itinerary items...]

Client -> create_itinerary_item({
  "collection_id": "6c5d9f61-2f09-4882-b277-8884b633d36b",
  "content_type": "location",
  "object_id": "fe7ee379-8a2b-456d-9c59-1eafcf83979b",
  "date": "2026-06-12",
  "order": 3
})
Server -> {"id": "5eb8c40c-7e36-4709-b4ec-7dc4cfa26ca5", ...}

Client -> reorder_itinerary({"items": [
  {
    "id": "5eb8c40c-7e36-4709-b4ec-7dc4cfa26ca5",
    "date": "2026-06-12",
    "order": 0
  },
  {
    "id": "a044f903-d788-4f67-bba7-3ee73da6d504",
    "date": "2026-06-12",
    "order": 1,
    "is_global": false
  }
]})
Server -> [...updated itinerary items...]
```

## Related docs

- [Advanced Configuration](../configuration/advanced_configuration.md)
- [How to use Voyage](../usage/usage.md)
