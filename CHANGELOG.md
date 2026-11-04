# Changelog

All notable changes to Magarr. Versions follow [semantic versioning](https://semver.org/).

## [0.1.0] - 2026-11-04

The first release: a magazine PVR in the style of Sonarr/Radarr, built in seven phases from
[the design brief](magarr-design-brief.md).

### Library
- Magazines with alternate titles, frequency, quality profile, root folder, tags and a search
  cutoff; issues by number, date, week, quarter, Vol/No or special name.
- Library scan: matches folders and files to magazines and issues, creates unmonitored magazines
  for unknown folders, and lists anything it can't place (with the reason) as unmapped.
- File-name parser for every common magazine naming style, including `YYMM` prefixes, glued names
  (`Crash94-Dec91`), Christmas and 13th-month specials, and one-off books in ad-hoc magazines.
- Naming scheme with live preview and collision checks; covers from the first issue's first page.
- CSV import, issue generation from the frequency, bulk edits, saved filters, custom poster order.

### Search, download and import
- Indexers: Newznab/Torznab, synced from Prowlarr; rate limits, caching and failure back-off.
- Decision engine: quality profiles, size limits, protocols, required and forbidden terms,
  blocklist, upgrades and cutoff.
- Download clients: SABnzbd, NZBGet, qBittorrent, Transmission, Deluge and rTorrent.
- Import: move, copy or hard link, renaming, upgrades into a recycle bin, remote path mappings,
  packs, manual import; copes with download folders it may read but not change.

### Automation
- RSS sync, upcoming issues added from each magazine's schedule, batched and resumable backlog
  search, automatic retry of failed downloads, "grab new specials".
- Wanted and Calendar pages.

### Operations
- Notifications: Discord, Slack, ntfy, Pushover and webhooks, with message templates.
- Health checks, scheduled tasks with history and "run now", weekly backups and restore, live logs.
- REST API with OpenAPI description ([docs/api/openapi.json](docs/api/openapi.json)).

### Security
- API key on every API route; bounded request bodies and fields; path-traversal guards on import;
  SSRF guard on configured URLs and on links from indexer feeds; security headers; secrets masked
  in the API and in logs.
