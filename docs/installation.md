# Installation

Magarr runs as a single Docker container: the web UI and the API on port **8282**.

## With Docker Compose

```yaml
services:
  magarr:
    image: ghcr.io/ahammerton/magarr:0.1   # or build it yourself: see "From source"
    container_name: magarr
    ports:
      - "8282:8282"
    volumes:
      - ./config:/config            # database, config.yaml, logs, backups
      - /srv/magazines:/magazines   # your magazine library
      - /srv/downloads:/downloads   # where your download client puts finished downloads
    environment:
      - TZ=Europe/London
    restart: unless-stopped         # also lets "restore a backup" restart Magarr
```

```sh
docker compose up -d
```

Open <http://your-server:8282>, then follow [Getting started](getting-started.md).

The tag `0.1` follows the latest 0.1.x release, and `latest` the newest release of any kind;
pin an exact version (`0.1.0`) if you prefer to upgrade by hand.

### From source

```sh
git clone https://github.com/ahammerton/magarr.git && cd magarr
docker compose up -d --build     # uses docker-compose.yml, which builds the image
```

Machine-specific mounts go in `docker-compose.override.yml` (git-ignored, loaded automatically);
`docker-compose.override.example.yml` shows the idea.

## Volumes

| Path in the container | What | Notes |
|---|---|---|
| `/config` | `magarr.db`, `config.yaml`, `logs/`, `backups/`, cover cache | Back this up (Magarr also makes weekly backups into it). |
| your library | the magazine folders | Add it as a **root folder** in Settings → Media Management. Any path works; `/magazines` is a convenient default. |
| your downloads | the download client's finished folder | Mount it at **the same path the download client uses** and nothing else is needed. Otherwise add a [remote path mapping](download-clients.md#remote-path-mappings). |

## User and permissions

The container runs as user **1000**, group **1000** by default, never as root. Magarr needs to:

- read and write `/config`;
- read, write and create folders in your library;
- read the download folders, and (to move rather than copy) rename and delete files in them.

To run as another user, for example to match a NAS share's owner:

```yaml
    user: "1001:100"
```

The `/config` folder must then belong to that user. If the download client writes files only it
can change, Magarr imports copies and tells you so: see
[Importing → permissions](importing.md#when-the-download-folder-is-read-only).

## Configuration

On first start Magarr writes `/config/config.yaml` with every setting and a generated API key.
Any setting can be overridden with an environment variable `MAGARR_<SECTION>__<KEY>`:

| Section | Key | Default | |
|---|---|---|---|
| `server` | `host`, `port` | `0.0.0.0`, `8282` | |
| `auth` | `api_key` | generated | used by the UI and by other apps |
| `auth` | `basic_auth_enabled`, `username`, `password` | off | see [Security](security.md) |
| `logging` | `level`, `json_format`, `file_enabled` | `INFO`, `false`, `true` | |
| `database` | `url` | SQLite in `/config` | |
| `downloads` | `poll_interval` | `30` | seconds between download client checks |

Example: `MAGARR_LOGGING__LEVEL=DEBUG`. Environment overrides are never written back to the file.

## Platforms

Images are built for `linux/amd64` and `linux/arm64` (64-bit Raspberry Pi, ARM NAS, Apple
Silicon).

## Behind a reverse proxy

Proxy everything to port 8282, including WebSocket upgrades for `/api/v1/ws/queue` (live queue).
Magarr serves from the root path; use a host name such as `magarr.example.lan`, not a sub-path.
Turn on [basic auth](security.md) before exposing Magarr beyond your own network.
