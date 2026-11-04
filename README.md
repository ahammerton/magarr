# Magarr

A self-hosted magazine PVR for Usenet and BitTorrent, in the style of Sonarr and Radarr.

Magarr keeps a library of magazines, finds new and missing issues on your indexers (directly or
through Prowlarr), sends them to your download client, and files the finished downloads under a
consistent name. It understands how magazines are actually numbered and named: monthly and weekly
dates, issue numbers, volumes, quarters, `2510`-style prefixes, Christmas issues and other specials.

- **Library**: scan an existing collection, match files to issues, list what can't be placed
- **Search**: Newznab/Torznab and Prowlarr; quality profiles, size limits, required and forbidden words
- **Download clients**: SABnzbd, NZBGet, qBittorrent, Transmission, Deluge, rTorrent
- **Import**: rename, upgrade, remote path mappings, manual import
- **Automation**: RSS sync, upcoming issues from each magazine's schedule, batched backlog search
- **Notifications**: Discord, Slack, ntfy, Pushover, webhooks
- **Operations**: health checks, scheduled tasks, weekly backups and restore, live logs, REST API

## Quick start

```yaml
# docker-compose.yml
services:
  magarr:
    image: ghcr.io/ahammerton/magarr:0.1   # or build from source (below)
    ports:
      - "8282:8282"
    volumes:
      - ./config:/config
      - /srv/magazines:/magazines
      - /srv/downloads:/downloads    # the same path your download client uses
    restart: unless-stopped
```

```sh
docker compose up -d
```

Open <http://localhost:8282> and follow [Getting started](docs/getting-started.md).

To build from source instead: clone this repository and run `docker compose up -d --build`.

## Documentation

The [guide](docs/README.md) covers [installation](docs/installation.md),
[the library](docs/library.md), [searching](docs/searching.md),
[download clients](docs/download-clients.md), [importing](docs/importing.md),
[automation](docs/automation.md), [notifications](docs/notifications.md),
[the system pages](docs/system.md), [upgrading](docs/upgrading.md), [security](docs/security.md),
the [API](docs/api.md) and [troubleshooting](docs/troubleshooting.md). Changes are in the
[changelog](CHANGELOG.md); how Magarr was designed and built is in the
[design brief](magarr-design-brief.md).

To run from source, run the checks or make a release, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

GPL-3.0. See [LICENSE](LICENSE).
