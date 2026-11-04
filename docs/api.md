# API

Everything the web UI does goes through Magarr's REST API, so anything you can do in the UI you
can script.

- **Reference**: Swagger UI at `/api/docs` on your Magarr, or the
  [OpenAPI description](api/openapi.json) in this repository.
- **Authentication**: the API key from `config.yaml` (`auth.api_key`), as an `X-Api-Key` header or
  `?apikey=`.
- **Conventions**: JSON with camelCase names; errors are `{"message": "..."}` with a 4xx status.
  Lists that can grow take `page` and `pageSize` (at most 1000) and return the total in an
  `X-Total-Count` header.
- **Live queue**: a WebSocket at `/api/v1/ws/queue?apikey=...` sends the queue whenever it changes.

## Examples

```sh
KEY=...    # auth.api_key from /config/config.yaml
URL=http://localhost:8282

# Magazines, with statistics
curl -H "X-Api-Key: $KEY" "$URL/api/v1/magazine"

# Add a monitored monthly magazine
curl -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"title": "Wired", "frequency": "monthly", "monitored": true}' "$URL/api/v1/magazine"

# What's wanted, 20 at a time
curl -H "X-Api-Key: $KEY" "$URL/api/v1/wanted?page=1&pageSize=20"

# Search for issues now and grab the best release (runs in the background)
curl -H "X-Api-Key: $KEY" -H "Content-Type: application/json" \
     -d '{"issueIds": [37, 38]}' "$URL/api/v1/wanted/search"

# Run RSS sync now
curl -X POST -H "X-Api-Key: $KEY" "$URL/api/v1/system/task/rss/run"

# Health
curl -H "X-Api-Key: $KEY" "$URL/api/v1/system/health"
```
