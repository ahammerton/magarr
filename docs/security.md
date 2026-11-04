# Security

## The API key

Every `/api` request needs the API key (the `X-Api-Key` header or `?apikey=`), the WebSocket too.
The web UI gets the key from `/initialize.json`, which is open while basic auth is off: anyone who
can reach the port can use Magarr. That's the usual arrangement for apps on a home network, the
same as the Arr apps with authentication disabled.

## Basic auth

Before exposing Magarr beyond your own network (port forwarding, a public reverse proxy), turn on
basic auth in `config.yaml`:

```yaml
auth:
  basic_auth_enabled: true
  username: you
  password: a-long-password
```

The UI and `/initialize.json` then need the username and password; `/api` accepts either them or
the API key. Use HTTPS (a reverse proxy) so they aren't sent in the clear.

## What Magarr will connect to

URLs you configure (indexers, Prowlarr, download clients, notifications) may be on your own
network: that's where those services live. Magarr never connects to link-local addresses (such as
the cloud metadata service at `169.254.169.254`), multicast or unspecified addresses, or anything
but `http://` and `https://`.

Links that arrive **from indexers** (release downloads, and every redirect they lead to) must point
at the public internet or at that indexer's own address, so a hostile feed can't make Magarr reach
your router or other devices. Notifications don't follow redirects.

## Other protections

- Request bodies are limited (1 MiB; CSV import 6 MiB; backup upload 2 GiB) and every field has a
  size limit.
- Imports only write inside the magazine's folder; manual import accepts only plain magazine files
  by full path (no `..`, no symbolic links).
- Indexer responses are parsed with entity expansion and DTDs disabled.
- The UI is served with a content security policy (no inline or third-party scripts), and with
  `X-Frame-Options: DENY`, `nosniff` and `no-referrer`.
- Secrets (API keys, passwords, webhook URLs) are masked in API responses and in logs.
- The container runs as an unprivileged user.

Report security problems privately: see [SECURITY.md](../SECURITY.md).
