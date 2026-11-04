# Design Brief: Magarr — A Magazine PVR for Usenet & BitTorrent

> **Working title:** Magarr (verify name availability before publishing; no existing magazine-focused *arr app exists today — Mylar3 covers *comics*, Readarr covers *books*, and nothing in the Servarr ecosystem handles periodicals with an issue-based model).

---

## 1. Vision & Goals

### 1.1 What it is
Magarr is a self-hosted PVR (Personal Video Recorder, magazine edition) in the style of Sonarr/Radarr/Lidarr. It monitors, searches, downloads, sorts, and renames **magazine issues** sourced from Usenet indexers and BitTorrent trackers. It is a *management* application only — it does not render, preview, or serve the downloaded files. A separate app (e.g., a file browser, Komga-style reader, or Calibre-web) handles display.

### 1.2 Core value proposition
- Add a magazine by name; Magarr tracks its publication schedule and back-catalogue of issues.
- Automatically discovers, grabs, and imports new issues from configured indexers.
- Organizes downloads into a clean, predictable folder/naming scheme consumable by any downstream reader app.
- Supports both Usenet (NZB) and BitTorrent via multiple download client integrations.
- Integrates with Prowlarr/Jackett so indexers are configured once, not per-app.

### 1.3 Non-goals (explicitly out of scope for v1)
- No built-in reading, previewing, or metadata art gallery beyond a poster/cover cache.
- No support for non-issue periodical content initially (e.g., rolling blog-style "issues", loose article packs) — defer to a later phase.
- No native support for private tracker *automation beyond standard Torznab* (no autobrr-style IRC announces in v1; consider as a plugin later).

---

## 2. High-Level Architecture

### 2.1 Recommended stack

| Layer | Choice | Rationale |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Fast to iterate in Claude Code, huge ecosystem (httpx, apscheduler, sqlalchemy). Alternatively .NET 8 if you want strict parity with the Servarr codebase — pick one and stay consistent. This brief assumes Python. |
| Database | **SQLite** (default) via SQLAlchemy | Zero-config for self-hosters; keep schema migration-ready for PostgreSQL support later. |
| Job scheduling | APScheduler or arq | RSS sync, queue polling, wanted-list scans. |
| Frontend | **React 18 + TypeScript + Vite** | Matches Arr UI patterns; dark theme first. |
| UI components | Mantine or Chakra UI | Table-heavy dashboards need a solid grid library (TanStack Table). |
| API style | REST + WebSocket (SignalR-equivalent) | Arr apps push live queue/calendar updates over sockets. |
| Packaging | Docker (multi-arch amd64/arm64) + single binary via PyInstaller (stretch) | Standard for the ecosystem. |

### 2.2 Process layout (single container, like Arr apps)
```
magarr/
├── backend/
│   ├── api/            # FastAPI routers
│   ├── core/           # config, logging, db, events
│   ├── domain/         # magazine, issue, release models
│   ├── indexers/       # newznab/torznab clients
│   ├── downloaders/    # sabnzbd, nzbget, qbittorrent, deluge, transmission, rtorrent
│   ├── pipeline/       # search → decide → grab → import
│   ├── importers/      # parsing, matching, file ops
│   └── notifications/  # discord, slack, webhook, ntfy
├── frontend/
└── docker/ (Dockerfile, docker-compose.yml example)
```

### 2.3 The core pipeline
Every automated and manual action flows through one state machine:

```
Issue Wanted ──► RSS/Backlog Search ──► Indexer Query (Torznab/Newznab)
      ▲                                    │
      │                                    ▼
      │                           Release Parsing (title, year, month,
      │                           issue number, format, source)
      │                                    │
      │                                    ▼
      │                            Decision Engine
      │                    (quality, size caps, profile, rejection rules)
      │                                    │
      │                                    ▼
      │                              GRAB ──► Download Client
      │                                    │
      │                              Track in Queue (poll client API)
      │                                    │
      │                                    ▼
      │                           Import (move/rename to library)
      │                                    │
      └─────────── History / Notifications ◄─┘
```

---

## 3. Domain Model

The single hardest problem in a magazine app vs. Sonarr is the **issue model** — there is no global metadata provider for magazines (no TVDB/TMDB equivalent). Design for that from day one.

### 3.1 Entities

**Magazine (series-level)**
- `id`, `title` (canonical), `alternate_titles[]`, `publisher`, `language`, `category` (e.g., Technology, Science, Fashion, Gaming), `frequency` (weekly, monthly, quarterly, ad-hoc), `first_issue_year` (optional), `tags[]`, `quality_profile_id`, `root_folder_id`, `monitored` (bool), `images` (poster/cover URLs — user-provided or scraped from indexers), `issue_naming_template`, `notes`.

**Issue**
- `id`, `magazine_id`, `issue_number` (string, e.g. `"128"` or `"2024-05"`), `title` (optional special title), `publish_date`, `cover_url`, `monitored`, `status` (`missing` | `wanted` | `downloaded` | `ignored`), `file_id` (nullable FK).

> **Key design decision:** `issue_number` is a **string**, not an integer. Magazine numbering is inconsistent (volume/issue combos, year-month schemes, "Special Edition", numbering restarts). Store a normalized sort key (`sort_index` float) alongside.

**File**
- `id`, `issue_id`, `relative_path`, `size`, `format` (PDF | EPUB | CBZ | CBR | ...), `quality` (parsed), `edition` (optional), `date_added`.

**Release (transient search result)**
- Parsed from indexer response: `release_title`, `indexer_id`, `guid`, `download_url`, `protocol` (`usenet`|`torrent`), `size`, `seeders`/`leechers` (torrent), `age`, `parsed` → `{ magazine_title, issue_number, year, month, format, source }`, `rejection_reasons[]`.

**Download (tracked queue item)**
- `id`, `issue_id`, `release_json` (snapshot of grabbed release), `download_client_id`, `external_id` (client-side id/hash), `status` (`queued`|`downloading`|`completed`|`failed`|`warning`), `progress`, `output_path`.

**History** — immutable event log: grab, import, failure, upgrade, delete.

### 3.2 Database schema sketch (SQLAlchemy-level)
```
magazines ──< issues >── files
magazines >── quality_profiles
indexers (id, name, protocol, url, api_key, priority, caps_json, tags[])
download_clients (id, name, type, host, port, credentials, category, priority)
quality_profiles ──< quality_profile_items (quality, allowed, max_size_mb, upgrade_until)
naming_config (id, magazine_pattern, issue_pattern, replace_illegal, separators)
root_folders (id, path, default)
```

### 3.3 Folder & naming conventions
```
/<root>/<Magazine Title (Year started)>/Season 2014/              # Sonarr-style "season" = year
    Magazine Title - 2014-07 - Issue 045.pdf
```
- Default pattern tokens: `{magazine_title}`, `{issue_number}`, `{year}`, `{month}`, `{day}`, `{publish_date}`, `{format}`, `{quality}`.
- Configurable per magazine; validate patterns render uniquely (collision detection).

> **Change (after Phase 4):** the year folder is now optional and **blank by default**, so issues go directly in `<Magazine Title (Year started)>/`. Komga and similar readers treat each folder as a series, so a `Season 2014`/`2014` sub-folder showed up as a series named after the year. Set the year folder pattern (e.g. `{year}`) under Settings → Media Management to get the layout above. Migration `0006` switches installs still on the old `Season {year}` default to blank and leaves custom patterns alone; when an import replaces a file, folders it leaves empty are removed (never the magazine folder itself).
- Store issues grouped by publication **year** as the container — it sorts naturally and maps to how releases are named on indexers.

---

## 4. Key Differentiators & Hard Problems

1. **No metadata provider.** The app must:
   - Let users manually add issues (bulk CSV import of `title, issue, date` lists).
   - Auto-suggest issues for weekly/monthly magazines by generating expected issue slots from `frequency` + `first_issue_date` ("issue calendar").
   - Match releases to issues via parsed naming, with fuzzy fallback (rapidfuzz) and confidence thresholds.
2. **Issue numbering chaos.** Parser must handle: `Magazine.Name.2024.05.pdf`, `MagName.Issue.128.May.2024`, `MagName.Vol12.No3.2024`, `MagName.Special.Collectors.Edition.2024`, and year-week formats.
3. **Huge back-catalogs.** Magazines may have 1000+ missing issues. Backlog search must be **batched, rate-limited, and resumable** — never fire N queries per indexer per issue in one burst.
4. **Weekly churn.** RSS sync + automatic "mark new issue as wanted" is the bread-and-butter flow — it must be rock solid.
5. **Upgrades.** Like Radarr, if a better quality/format release appears, replace the existing file (PDF→scanned-hi-res, or missing pages version).

---

## 5. Phased Implementation Plan

> Each phase ends with a **working, tested, manually-verifiable increment**. Build the backend API first, UI per phase immediately after its backend lands. Write unit tests for parsers/decision engine, integration tests (with mocked indexer/download clients) for pipelines.

### Phase 0 — Scaffolding & Foundations (1 week)
**Deliverable: app boots, empty dashboard renders, config persists.**
- Repo layout (backend/frontend), devcontainer or `docker compose` with hot reload.
- Config service: YAML + env override, bound to a settings schema (Pydantic).
- SQLite + Alembic migrations; base model + repository layer.
- Logging (structured, log levels), health endpoints `/health`, `/api/v1/system/status`.
- Auth: API key middleware from day one (arr apps use forms auth; a single API key + optional basic auth is fine for v1).
- Frontend shell: Vite + React, dark theme, app layout (sidebar: Library, Calendar, Activity, Wanted, Settings, System).
- CI: lint (ruff, eslint), tests (pytest, vitest), GitHub Actions.

**Definition of done:** `docker compose up` gives a styled empty UI with a working System → Status page.

> **Status: ✅ Phase 0 complete (2026-10-15).**
> - ✅ `docker compose up --build` → container healthy on :8282, dark Mantine UI, System → Status shows live data from `/api/v1/system/status`.
> - ✅ Repo layout + hot reload: `docker-compose.dev.yml` (uvicorn `--reload` + Vite HMR on :5173, polling enabled for macOS VM mounts).
> - ✅ Config: Pydantic schema, `/config/config.yaml` written on first boot with generated API key, `MAGARR_<SECTION>__<KEY>` env overrides (never persisted). Key survives `docker compose down`/`up`.
> - ✅ SQLite + Alembic: baseline revision `0001` applied on startup; test guards that models and migrations stay in sync.
> - ✅ Base model (`ModelBase`: id, created_at, updated_at) + generic `Repository` with pagination.
> - ✅ Structured logging: text/JSON console, rotating JSON file in `/config/logs`, configurable level.
> - ✅ `/health` (open, checks DB) and `/api/v1/system/status` (API key).
> - ✅ Auth: API key via `X-Api-Key` / `?apikey=`; optional basic auth for UI + API.
> - ✅ Frontend shell: sidebar Library, Calendar, Activity, Wanted, Settings, System → Status; strings externalized in `src/i18n/en.json`.
> - ✅ Lint/tests pass locally: ruff check + format, pytest (32), eslint, tsc, vitest (14), vite build.
> - ❌ CI workflow (`.github/workflows/ci.yml`: lint, tests, multi-arch image build) is written but has not run on a CI runner yet; the repo has no remote.
> - Layout note: the Python package lives at `backend/magarr/{api,core,migrations}`, not `backend/api` etc. as sketched in §2.2, so that it installs as the `magarr` package.

### Phase 1 — Domain Core & Library Management (1–2 weeks)
**Deliverable: user can CRUD magazines and issues; library on disk is scannable.**
- Full domain models + migrations (§3.2).
- CRUD APIs: magazines, issues, root folders, quality profiles (default profile seeded), naming config.
- **Library scan/import**: walk root folder, parse existing paths into magazine/issue records (fuzzy match to known magazines, "unmapped files" list).
- Bulk CSV issue import + "generate expected issues" from frequency (fills future calendar slots).
- UI: Magazine list (poster grid + table toggle), magazine detail (issue table with status badges, per-issue monitor toggle), add-magazine wizard (title, alt titles, frequency, quality profile, tags, root folder).
- Manual issue search stub: query indexers not yet implemented — return parsed dummy data to prove the UI flow.

**Definition of done:** user adds "National Geographic", generates 24 monthly issues, marks 6 wanted.

> **Status: ✅ Phase 1 complete (2026-10-15), verified by the user.**
> - ✅ Post-release fix `82e9c1a`: sidebar sections with sub-pages (Library, Settings, System) didn't navigate when clicked. Unit and Playwright tests now click each section.
> - ✅ Definition of done verified three ways: Playwright e2e in a real browser against a real backend (`npm run e2e`), the pytest `test_definition_of_done`, and by hand against the Docker container's API.
> - ✅ Domain models + migration `0002`: magazines, issues, files, quality profiles (+ items), naming config, root folders, unmapped files. Indexer and download-client tables (in the §3.2 sketch) are deferred to Phases 2–3, so no feature is built ahead of its phase.
> - ✅ CRUD APIs: `/magazine`, `/issue` (+ `/issue/bulk`), `/rootfolder`, `/qualityprofile` + `/quality`, `/config/naming` (+ `/preview`). The default "Any" profile and naming scheme are seeded on startup.
> - ✅ Library scan (`POST /library/scan`): first-level folders are matched to magazines (exact folder name, then rapidfuzz on title/alternate titles, threshold 90). Files are parsed into issues; unknown issues are created unmonitored; moved and deleted files are reconciled. Unmatched files go to `GET /library/unmapped` with a reason. Refuses to run if a root is empty but files are recorded (unmounted-drive guard).
> - ✅ CSV import (`POST /magazine/import`): columns magazine, issue, date (ISO only), issue_title. Per-row errors don't abort the import; optionally creates missing magazines.
> - ✅ Generate expected issues (`POST /magazine/{id}/generate-issues`) for weekly / monthly / quarterly frequencies; idempotent.
> - ✅ Naming: tokens per §3.3, validation (must include `{issue_number}`, no unknown tokens or path separators), and case-insensitive collision detection on save. The brief's example path is covered by a golden test.
> - ✅ UI: poster grid / table toggle (remembered), filter, scan; 3-step add wizard; detail page with status filter, per-issue monitor toggle, bulk mark wanted / unmonitor / ignore, generate, add/edit/delete issue; CSV import page; unmapped files page; Settings → Media Management (root folders, naming with live preview) and Profiles (order, allowed, max size, cutoff).
> - ✅ Manual search stub (`POST /issue/{id}/search`): sample release names run through the real parser and matcher, flagged `stub: true`. The UI labels them as sample data, and Grab is disabled.
> - ✅ Filename parser covers every §4.2 format; 39-name corpus in `tests/test_parsing.py`. (Phase 2 asks for ≥200 real release names.)
> - ✅ Tests: pytest 153, vitest 42, Playwright 2; ruff, eslint and tsc clean. CI gains an e2e job, which, like the rest of CI, has not run on a runner yet.
> - Deviations: magazine `images` is a single `poster_url`; when it is blank the UI shows the cover of the earliest downloaded issue (first page of a PDF, the declared cover of an EPUB, the first image of a CBZ), rendered with pdfium and cached under `<config>/cache/covers`; tags are free-text strings on the magazine rather than a tag table; the naming config gains `year_folder_pattern` (for the §3.3 "Season YYYY" folder) and `colon_replacement` in place of the unspecified `separators`. A library scan turns each unknown folder that holds magazine files into a new, unmonitored magazine named after the folder (`Viz (1982)` → Viz, first issue year 1982; frequency guessed from the issue dates) and imports its files; a folder whose title already exists in another root folder stays unmapped. Special issues are issues of their magazine named "name + year": a YYMM prefix with month 13 (the year's extra issue) is "Christmas Special 2024" when the name says Christmas/Xmas, otherwise what the file adds to the magazine's title ("Ship Handbook 2025") or "Special 2024", dated December so it sorts after the December issue; "Xmas", "Christmas" and "Christmas Special" all become "Christmas Special <year>" so files and releases agree. In ad-hoc magazines a file with no number or date becomes an issue named by its title (collections of one-off books). The expected-issue schedule follows regular issues only, and a per-magazine "Grab new specials" lets RSS sync add and grab specials it sees. Issue status is derived from the file and the monitored flag: wanted = monitored with no file, missing = unmonitored with no file; ignored sticks until the issue is monitored again.

### Phase 2 — Indexer Layer: Torznab/Newznab + Prowlarr (1–2 weeks)
**Deliverable: real search results appear in the manual search UI.**
- Generic Torznab/Newznab client (`/api?t=search&q=...`, caps parsing, pagination, categories — see `t=caps` for supported `magazine` category; map common cat IDs e.g. 7010/7020/7030).
- Indexer manager: add/edit/test indexers; priority ordering; per-indexer enable/disable; tag scoping.
- **Prowlarr sync integration**: pull configured apps indexers from Prowlarr's `/api/v1/indexer` (implement the *consumer* side; users can also add indexers manually).
- Rate limiting + per-indexer query cache; timeouts; error handling that marks an indexer disabled after consecutive failures.
- Release parser v1: regex engine for the formats in §4.2, plus size/seeders/age extraction; unit-test against a corpus of ≥200 real release names.
- Manual search UI: modal per issue with parsed columns (title, issue, age, size, seeders, indexer) and reject-reason tooltips.

**Definition of done:** searching a wanted issue against Prowlarr returns parsed, sortable results.

> **Status: ✅ Phase 2 complete (2026-10-15), verified by the user in Docker against their Prowlarr.**
> - ✅ **Definition of done, verified against a real Prowlarr** (2.5.2, NZBgeek): sync imported `NZBgeek (Prowlarr)` as `http://<prowlarr>:9696/1/api`. Searching wanted issue National Geographic 2026-06 returned 44 parsed results; the English `National.Geographic.June.2026.HYBRID.MAGAZINE` was approved and every other result rejected with the right reason (spin-off titles, Spanish edition). Sorting checked in a real browser on that data. Run both natively and inside the Docker image.
> - ✅ Newznab/Torznab client (`magarr/indexers/`): caps, category search, pagination that follows `total`, Torznab seeders/peers, hardened XML (defusedxml), and clear errors for Newznab error codes, HTTP failures and timeouts.
> - ✅ Indexer manager: CRUD, connection test, priority, enable/disable, tag scoping, categories; API keys masked on read.
> - ✅ Prowlarr consumer sync: connection details follow Prowlarr; user edits to categories, tags and enabled are kept; manual indexers are never touched.
> - ✅ Rate limiting, 15-minute response cache, 30 s timeout, failure backoff (paused after 3 failures, 5 min up to 24 h).
> - ✅ Release parser v1, with **200 real NZBgeek titles** in `backend/tests/corpus/releases.tsv` (harvested 2026-10-15 with 18 API calls, picked for structural variety, each expected value reviewed by hand) plus 42 hand-written titles. Two real titles with non-English month names are recorded as known gaps (strict xfail). Real data drove: scene language tags with rejection when they differ from the magazine's language, bracketed dates, glued `TruePDF`, day/month ranges across months and years, US-style numeric dates, French `N4690` numbering, false-positive pack fixes, and a matcher bug where an overlapping match skipped the rest of the text.
> - ✅ Search UI: sortable real results, rejection tooltips, per-indexer error and pause notices; Settings → Indexers with Prowlarr connection and health status.
> - ✅ Security fixes found during real verification: (1) httpx logged every indexer URL, API key included, at INFO. Now silenced, and every log handler redacts `apikey=` / `X-Api-Key` / passwords, which also covers stored error messages; covered by a regression test. (2) Search results no longer include download URLs, because Prowlarr's embed its API key; Phase 3 grabs server-side.
> - ✅ Tests: pytest 444 (+2 xfail gaps), vitest 54, Playwright 4 (full flow against a stdlib fake Prowlarr).
> - Deviations: indexer health lives on the indexer row; search results come in the HTTP response rather than over WebSocket. Numeric dates without a leading year are read US-style (MM DD YYYY), as observed on NZBgeek; truly ambiguous ones such as "03 04 2025" are excluded from the corpus.

### Phase 3 — Decision Engine & Grabbing (1 week)
**Deliverable: clicking "Grab" sends the release to a download client and tracks it.**
- Decision engine: parse-match confidence ≥ threshold → quality allowed? size ≤ profile cap? protocol allowed? custom filter rules (must contain / must not contain, regex) → ranking (quality desc, then seeds, then age/size heuristics).
- Quality/size profiles: per-format quality tiers (e.g., PDF < EPUB < "Hi-Res Scan"), upgrade-until flag.
- Download client abstraction: `IDownloadClient` interface (`add`, `status`, `remove`, `test`) with per-client config schema.
- Implement first client: **qBittorrent** (Web API: add torrent via URL, category support, status polling).
- Grab history records (with full release JSON snapshot).
- Queue polling loop (30s): update progress, detect completion/failure.
- Failed-download handling: mark issue wanted again, blacklist that release, optionally pick next-best automatically.

**Definition of done:** end-to-end test with qBittorrent container in docker-compose: grab → complete → import trigger fires (import itself is Phase 4, so completion just writes history + moves state to `pending_import`).

> **Status: ✅ Phase 3 complete (2026-10-21).**
> - ✅ **Definition of done**: `scripts/qbittorrent-integration.sh` starts a real qBittorrent container (linuxserver 5.0.2, pre-seeded login), and Magarr searches a Torznab feed, grabs, polls, and moves the download to `pending_import` with history `grabbed` → `download_completed` and the right output path. The test builds its own torrent and pre-places the data, so qBittorrent completes by verifying it, with no network transfer. Magarr's computed info hash matches qBittorrent's. Also runs in CI.
> - ✅ Decision engine (`pipeline/decision.py`): after the Phase 2 match checks, quality allowed, size within the quality's cap, protocol allowed, must / must-not-contain terms (text or `/regex/`), blocklist, already downloading, and upgrade/cutoff against an existing file. Approved releases are ranked by profile quality order, then seeders, then age, then indexer priority.
> - ✅ Profiles gain `protocols`, `must_contain`, `must_not_contain`; migration `0004` gives existing profiles safe defaults (upgrade tested against a populated database).
> - ✅ `DownloadClient` interface (`test`, `add`, `items`, `remove`) with per-client settings schemas served to the UI. **SABnzbd and qBittorrent** are both implemented (the brief allows folding Usenet clients into Phase 3; the user's setup is SABnzbd). Magarr fetches and validates the NZB/.torrent itself and uploads it, follows magnet redirects, and computes torrent info hashes (small bencode reader).
> - ✅ Grab (`POST /release/grab`) by (indexer, guid) from a server-side release cache, so download URLs, which embed indexer keys, never reach the browser. Per-issue grab locks. History records a key-free release snapshot.
> - ✅ Queue polling (default 30 s, `downloads.poll_interval`): queued / downloading / paused progress, completed → `pending_import`, failed → history + blocklist + optional automatic grab of the next-best approved release. An item missing from the client becomes a *warning* after 3 polls, not a failure, so a manual removal doesn't trigger re-downloads.
> - ✅ UI: Settings → Download Clients (fields generated from the schema, test, priority, enable, failed-download toggle); Grab in search results (rejected releases need confirmation); download status on issue rows with live refresh; profile protocol and term rules.
> - ✅ Tests: pytest 487 (+1 integration, +2 xfail gaps), vitest 64, Playwright 5 (including grab → fake SABnzbd → "Ready to import" in a real browser).
> - Bug fixed on the way: closing the search window could crash the page (Phase 2 latent).
> - ✅ **Real SABnzbd** (user's, 5.1.3, 2026-10-21): Prowlarr search for National Geographic 2026-06 → grab of `National.Geographic.June.2026.HYBRID.MAGAZINE` into category `books` → tracked Queued → Downloading → Post-processing → `pending_import` in about 25 s; output `/data/usenet/complete/National.Geographic.June.2026.HYBRID.MAGAZINE`. No keys in any log.
> - ✅ Post-release fix (2026-10-21): migration 0004 failed on a real database (`FOREIGN KEY constraint failed`). SQLite batch migrations rebuild tables, and with foreign keys enforced the profile table that magazines reference couldn't be dropped. That left a half-applied migration and a crash-looping container. Migrations now run with foreign-key enforcement off, then verify with `PRAGMA foreign_key_check`, and the database file is backed up (`magarr.db.pre-<new>-from-<old>.bak`) before any upgrade. Regression test uses a populated database. The user's database was repaired (empty leftover tables dropped, data intact) and upgraded.
> - Note for Phase 4: clients report paths as *they* see them (`/data/usenet/...` here), which may differ from Magarr's view of the same files; import will need remote path mappings.
> - Deviations: grab takes `{guid, indexerId, issueId}` instead of `{release, issueId}` (keeps keys server-side). No Queue/History pages yet (Phase 4 per the brief); history and queue are available over the API. Polling uses an asyncio task; a scheduler (Tasks page) is Phase 6.

### Phase 4 — Import Pipeline & File Organization (1–2 weeks)
**Deliverable: completed downloads land in the library, correctly named.**
- Usenet first-class too: **SABnzbd** + **NZBGet** clients (Phase 3 was torrent-only to keep scope tight; do these here or fold into Phase 3 if velocity allows — either is acceptable, keep interface stable).
- Import worker: locate downloaded files (client output path + category), verify single-issue packs vs multi-issue packs (a pack release fills N issues at once — critical for magazine backlogs).
- Multi-file/import decisions: interactive vs automatic (per config), sample-file detection, obfuscation/renaming tolerance.
- File operations: move (atomic across same FS), rename per pattern, collision handling (` - copy`), permission/chown options.
- Upgrade flow: compare new file vs existing (quality/format/size), keep better per profile, delete replaced (with recycle bin option).
- UI: Activity → Queue page (live via WebSocket), History page (filterable), Manual Import from folder.

**Definition of done:** a full qBittorrent/SABnzbd download imports as `Magazine Title (1999)/Season 2014/Magazine Title - 2014-07 - Issue 045.pdf` and appears green in the issue grid.

> **Status: ✅ Phase 4 complete (2026-10-21).**
> - ✅ **Definition of done (automated, real qBittorrent container)**: grab → qBittorrent completes → imported through a remote path mapping (qBittorrent's `/downloads` → host folder) as `National Geographic (1888)/National Geographic - 2025-01 - Issue 2025-01.pdf` (default naming, no year folder; see the §3.3 change note). The issue shows Downloaded; quality is PDF Hi-Res from the release name; the source stays for seeding. Also in CI. The browser e2e runs the same flow through a fake SABnzbd that writes to a fake NAS folder, with the mapping added in the UI.
> - ✅ **Real setup** (a real SABnzbd 5.1.3 and NAS share, mounted in the container at `/data`, the same path SABnzbd uses): Manual Import in copy mode of last week's National Geographic June 2026 (73 MB) into the existing library at `/data/media/books/magazines` → `National Geographic/2026/National Geographic - 2026-06 - Issue 2026-06.pdf` (the user's `{year}` folder pattern), byte-identical; SABnzbd's folder untouched.
> - ✅ Import pipeline (`importers/importer.py`): magazine files found (junk and samples skipped). One file goes to the grabbed issue even when obfuscated; packs fill every issue they match; the best format per issue wins. Upgrade check against the profile. Move (Usenet; atomic, or copy-and-rename across filesystems) or hard link / copy (torrents); `- copy` collision handling; chmod/chown; recycle bin. The old file is only disposed of after the new one is in place, and restored if the transfer fails. After a full Usenet move, a junk-only folder is deleted and the client told to forget the item.
> - ✅ Remote path mappings (longest prefix per client host). A path Magarr can't see waits with a hint and imports automatically once a mapping is added.
> - ✅ NZBGet client (JSON-RPC), behind the Phase 3 interface.
> - ✅ Manual import (any folder, or a download needing attention), with suggestions and warnings; queue actions (retry import, remove with optional client delete and blocklist); history filters.
> - ✅ UI: Activity → Queue (live over WebSocket `/api/v1/ws/queue`, polling fallback), History (filterable, paged), Manual Import; Settings → Media Management → Importing; Settings → Download Clients → Remote path mappings.
> - ✅ Tests: pytest 522 (+1 integration, +2 xfail), vitest 75, Playwright 6.
> - Bugs fixed on the way: NZBGet dropped the post-processing message; the poller wasn't given the event bus, so live queue updates only arrived on the 30 s heartbeat (regression test fails without the fix).
> - Deviations: the WebSocket is at `/api/v1/ws/queue` (not `/ws/queue`) so the API-key middleware and dev proxy cover it. Packs are still rejected for *automatic* grabs (reason explains that a manual grab imports every issue in the pack).

### Phase 5 — Automation: RSS Sync, Wanted List, Backfill (1 week)
**Deliverable: set-and-forget operation.**
- RSS sync task per indexer (cached, `t=search&rid`/q-less caps mode where available; else query-based): new releases matched against monitored magazines/issues.
- Automatic "expected issue" generation on schedule (weekly/monthly roll) — new issues become wanted automatically.
- Backlog/wanted search: scheduled job that searches wanted issues oldest-first, batched (e.g., 10 issues × interval, resumable cursor), respects indexer rate limits; stops per issue after first successful grab.
- Blacklist/auto-retry with next-best release on failure (configurable retries).
- UI: Wanted page (filter by magazine/status), Calendar page (publish-date view of expected/downloaded issues), global toggle "monitored", per-magnet cutoff options ("only issues newer than 2010").

**Definition of done:** a newly posted issue of a monitored magazine is grabbed with zero user interaction.

> **Status: ✅ Phase 5 complete (2026-10-21).**
> - ✅ **Definition of done** (Playwright, `e2e/automation.spec.ts`): a monitored monthly magazine with only last month's issue; Magarr adds this month's issue as wanted by itself; the issue is then posted to the (fake) indexer's feed, and RSS sync grabs it (history source "RSS sync"), SABnzbd (fake) downloads it and it is imported and renamed, with no clicks after setup. The e2e server runs automation in fast-forward (`automation.minute_seconds`), and a global setup pauses it so earlier phases' tests are unaffected.
> - ✅ RSS sync (`pipeline/automation.py`): each indexer's newest releases via a search with no term (how Newznab/Torznab and Prowlarr serve RSS), never cached; only releases not seen before are evaluated (bounded per-indexer guid memory). An empty feed falls back to one title search per wanted magazine. Matches go through the same parse/match checks and decision engine as interactive search; the best approved release per issue is grabbed under the issue lock. No indexer calls when nothing is wanted. Verified read-only against the user's Prowlarr/NZBgeek: 100 newest magazine releases (~2 days), so a 15-minute interval leaves no gaps.
> - ✅ Expected issues (`domain/expected.py`): each monitored magazine's schedule continues from its latest dated issue in the same numbering style (`2026-07`, `2026-W27`, `2026-Q3`, or `361`), up to a lookahead (default 45 days) so early releases have an issue to match. Magazines whose latest issue is more than six periods old are treated as no longer published (no invented issues); otherwise at most the last two missed periods are filled. Hourly.
> - ✅ Backlog search: batched (default 10 per hour), never-searched issues first, oldest first, then least recently searched; `issues.last_searched_at` is the resumable cursor, and an issue is searched at most once a day. Issues more than a week in the future and issues before the magazine's cutoff are skipped. If every indexer fails, the batch stops without moving the cursor. Rate limits: jobs run one at a time and share the per-indexer limiter; identical queries hit the indexer cache.
> - ✅ Blocklist/auto-retry: failed downloads were already blocklisted with an optional grab of the next-best release (Phase 3); retries are now capped per issue (`maxRetries`, default 3).
> - ✅ UI: **Wanted** (wanted/unmonitored, filter by magazine, paged, last searched, search selected in the background, (un)monitor); **Calendar** (Monday-first month grid, list on phones, status colours, unmonitored toggle); **Settings → Automation** (master switch = the global "monitored" toggle, RSS/backlog intervals with minimums of 10/15 minutes, batch size, lookahead, when each job last ran); per-magazine "Only search issues published after" (the cutoff); retry limit under Download Clients; History shows how a release was found.
> - ✅ Tests: pytest 582 (+1 integration, +2 xfail), vitest 88, Playwright 7.
> - Fixed on the way: `GET /api/v1/issue/{id}` didn't include the issue's current download (the list did).
> - Deviations: the scheduler is a small asyncio loop (like the Phase 3 poller) rather than APScheduler; job status is in memory and shown on Settings → Automation (a Tasks page with run-now and persistent history is Phase 6). The automation settings, the backlog cursor, the retry limit and the search cutoff are stored by migration `0007`. Per-indexer RSS/automatic-search toggles are not in the brief and were left out.

### Phase 6 — Remaining Download Clients, Notifications, Polish (1–2 weeks)
**Deliverable: ecosystem parity.**
- Additional download clients: **Deluge, Transmission, rTorrent** (and NZBGet if deferred). All behind the Phase 3 interface.
- Notifications: Discord, Slack, generic Webhook, ntfy, Pushover; events: grab, import, upgrade, failure, health warning. Templatable message text.
- System pages: Logs (live tail), Tasks (scheduled jobs with run-now), Backup/Restore (zip of config+db), Health (disk space, indexer/client reachability, bad root paths).
- UI polish: keyboard shortcuts, bulk operations, drag-drop poster grid, custom filters, theme tweaks.
- Optional v1.1 targets (document but don't build): Bazarr-style metadata export, Komga OPDS integration hooks, autobrr-style announce feed support.

**Definition of done:** a user can run the whole stack with Prowlarr + SABnzbd + qBittorrent + Discord notifications and never open the UI.

> **Status: ✅ Phase 6 complete (2026-10-21).**
> - ✅ **Definition of done** (Playwright, `e2e/unattended.spec.ts`, no page loaded): set up by API only (Discord notification, automation on, a monitored monthly magazine); Magarr adds this month's issue itself, RSS sync grabs it when it's posted, (fake) SABnzbd downloads it and it is imported, and Discord receives "Test from Magarr", "Grabbed Edge 2026-10 … Sent to SABnzbd (RSS sync)" and "Imported Edge 2026-10". Real-stack pieces: Prowlarr/NZBgeek RSS (Phase 5), SABnzbd and qBittorrent (Phases 3–4) and the user's real Discord webhook (test message delivered).
> - ✅ Download clients: **Transmission** (RPC, session handshake, labels), **Deluge** (Web JSON-RPC, daemon connect, re-login, Label plugin) and **rTorrent** (XML-RPC, d.custom1 label, defusedxml), behind the Phase 3 interface; NZBGet was done in Phase 4. `scripts/torrent-clients-integration.sh`: grab → real Transmission 4.1.3 / Deluge 2.2.0 / rTorrent 0.16.25 → complete → imported, all passing (it caught Deluge 2 lacking `daemon.info`).
> - ✅ Notifications: Discord, Slack, generic webhook, ntfy, Pushover; events grab, import, upgrade, failure, health; per-connection templates with `{tokens}` (first line = title), preview and test. Sent in the background and only after the change that caused them commits (a rolled-back grab never says "Grabbed").
> - ✅ System pages: **Logs** (live tail from an in-memory buffer, level filter, log file download), **Tasks** (expected issues, RSS, backlog, health check, backup, check downloads; schedule, last/next run, result, run now, persistent history in `task_runs`; a restart carries on from the recorded runs), **Backup/Restore** (weekly zip of a consistent SQLite copy + config.yaml, 7 kept; restore from a saved or uploaded zip is validated, staged, applied at the next start after a pre-restore backup, and Magarr restarts), **Health** (root folders missing/unwritable/low space, indexers, download clients tested, blocked imports, unseen download paths, failing notifications, paused automation; every 15 minutes, new problems notified; count on the sidebar).
> - ✅ UI polish: keyboard shortcuts (`?` help, `/` search, `g`+letter navigation, `n`, `t`), bulk operations on the library (monitor, profile, root folder, grab new specials, delete; all-or-nothing API), drag-and-drop poster order, custom saved filters and sorting, theme switch (dark/light/system).
> - ✅ Tests: pytest 671 (+4 integration against real clients, +2 xfail), vitest 115, Playwright 8.
> - Fixed on the way: log extras named like secrets (`api_key=`, `password=`) are now always masked (a test of the live log found it); backup names are unique to the millisecond.
> - Deviations: Discord URLs are validated by their `/api/webhooks/` path rather than the discord.com host, so Discord-compatible services (and the e2e fake) work. The scheduler remains the asyncio loop from Phase 5, extended with persistent runs. Settings form code is shared between download clients and notifications (`core/forms.py`).
> - Optional v1.1 targets (documented, not built): **metadata export** (Bazarr-style sidecar files: ComicInfo.xml / OPF next to each issue, so readers get titles, dates and covers); **Komga hooks** (trigger a Komga library scan after an import via its API, and match Komga series to Magarr magazines for read status); **announce feeds** (autobrr-style IRC/announce channels pushed to Magarr's grab API for releases faster than RSS).

### Phase 7 — Hardening & Release (1 week)
**Deliverable: public v1.0.**
- Security pass: API key everywhere, input validation, path traversal guards on import, SSRF guard on indexer URLs.
- Performance: indexes on all query columns, pagination on every list endpoint, N+1 audit.
- Docs: README with docker-compose example, wiki-style usage guide, API docs (OpenAPI is free with FastAPI — publish it).
- Multi-arch Docker build + release workflow (tagged semver), migration path documented (config only — no upgrades needed for v1).
- Load-test backlog search against a Prowlarr instance with 20 indexers (rate-limit correctness under pressure).

> **Status: ✅ Phase 7 complete except publishing (2026-11-02).** First public release is **0.1.0** (the user's choice of number, 2026-11-04): GitHub ahammerton/magarr, images on ghcr.io/ahammerton/magarr.
> - ✅ **Security pass.** *API key everywhere*: an audit test walks every route in the OpenAPI schema (and the queue WebSocket) and checks each refuses a wrong key. *Input validation*: every request field is bounded (a schema scan found 47 unbounded ones), and bodies are capped (1 MiB; CSV 6 MiB; backup upload streamed, 2 GiB), including chunked bodies. *Path traversal on import*: manual import takes only absolute paths without `..`, no symlinks, stays inside the download it belongs to, and won't take another issue's file; imports may only write inside the magazine's folder. *SSRF*: configured URLs may be on the LAN (home servers) but never link-local/metadata, multicast or unspecified; links from indexer feeds and their redirects must be public or the indexer's own host; notifications don't follow redirects. Also security headers (CSP without inline scripts, frame DENY, nosniff, no-referrer). Dependencies audited: certifi updated; React Router 7 (open redirect), Vite 8, Vitest 5 (critical dev advisory); remaining: 12 moderate advisories in ESLint's minimatch, dev-only and not shipped.
> - ✅ **Performance.** N+1 audit test: every list endpoint runs the same number of queries for 2 and 20 magazines (fixed Wanted, Calendar, History, Queue and the download poller). Every foreign key indexed (tested); `(status, last_searched_at)` and `(status, publish_date)` indexes (migration 0011); query plans checked for full scans and full sorts. On a 20,000-issue library: backlog query 5 ms, library 17 ms, Wanted 18 ms, Calendar 47 ms. Paging (`page`, `pageSize`, `X-Total-Count`) on magazines, issues, queue, blocklist and unmapped files, in addition to History and Wanted.
> - ✅ **Load test** (`scripts/load-test.sh`): 40-issue backlog batch against a stand-in Prowlarr with 20 rate-limited indexers (one slow, one failing) while searches from the UI run: 859 requests in 39 s, no indexer asked too quickly or twice at once, every issue searched. It found a real bug: separate sessions (backlog, RSS, UI) overwrote each other's indexer failure counts, so a failing indexer was never backed off; counts are now atomic and each search re-reads indexer health.
> - ✅ **Docs**: README with a docker-compose example; a guide in `docs/` (installation, getting started, library, searching, download clients, importing, automation, notifications, system, upgrading, security, API, troubleshooting); the OpenAPI description published as `docs/api/openapi.json` (CI checks it's current) and attached to releases; CHANGELOG.
> - ✅ **Release**: multi-arch image (`linux/amd64`, `linux/arm64`) with OCI labels, verified locally: both platforms built, started, served the UI and API and reported the version; also runs as another uid with a bind-mounted `/config`. `.github/workflows/release.yml` on a `vX.Y.Z` tag runs all checks, verifies the tag matches the code and changelog, pushes `X.Y.Z`/`X.Y`/`X`/`latest` (GHCR by default; any registry via variables) and creates the release. CI also runs the real Transmission/Deluge/rTorrent test. *Migration path*: documented in `docs/upgrading.md`: `config.yaml` never needs editing; database migrations run automatically after a backup; rollback by restoring the `.bak` or a backup.
> - ✅ Tests: pytest 734 (+5 integration/load, +2 xfail), vitest 115, Playwright 8; real qBittorrent, Transmission, Deluge and rTorrent; load test.
> - ✅ Name check (2026-11-02): no software or magazine project is called Magarr; PyPI and npm are free; on GitHub the bare `magarr` account exists (dormant, no repositories) and on Docker Hub the `magarr` namespace is taken (one test image), so publish under the owner's namespace (e.g. `ghcr.io/ahammerton/magarr`), not `magarr/magarr`. The name is kept.
> - Not done: publishing itself (the user's call).

---

## 6. API Surface (sketch, v1)

```
GET/POST/PATCH/DELETE  /api/v1/magazine(s)
POST                   /api/v1/magazine/import          # bulk CSV
GET/POST/PATCH         /api/v1/issue(s)                  # with ?magazineId=
POST                   /api/v1/issue/{id}/search         # manual search → releases[]
POST                   /api/v1/release/grab              # { release, issueId }
GET                    /api/v1/queue                     # active downloads
GET                    /api/v1/history
GET/POST/PATCH/DELETE  /api/v1/indexer(s)                # + /test, /sync-prowlarr
GET/POST/PATCH/DELETE  /api/v1/downloadclient(s)         # + /test
GET/POST/PATCH         /api/v1/config/{naming,media,profiles}
GET                    /api/v1/calendar?start&end
GET                    /api/v1/wanted
GET                    /api/v1/system/{status,logs,tasks,health,backup}
WS                     /ws/queue, /ws/history            # live updates
```

---

## 7. Non-Functional Requirements
- **Config & state portability:** everything in `/config` (db + yaml + images); one volume backup.
- **Concurrency safety:** one import worker; per-issue grab locks to prevent double-grabs from parallel RSS + backlog.
- **Observability:** structured logs, per-task run history, health checks for every external integration.
- **Localization-ready:** all user-facing strings externalized.
- **License:** GPL-3.0 (Servarr ecosystem convention).

---

## 8. Testing Strategy
- **Parser/decision unit tests** with a frozen corpus of real release names (commit new cases as users report misses).
- **Integration tests**: mocked Torznab server (pytest + respx), real qBittorrent/SABnzbd containers in CI via docker compose for the grab→import path.
- **UI tests**: component tests with MSW-mocked API; one Playwright smoke test per phase (add magazine → search → grab → import).
- **Golden-file tests** for naming pattern rendering.

---

## 9. Prompting Guidance for Claude Code
- Implement strictly phase-by-phase; do not jump ahead (don't build RSS sync before the grab flow is green).
- After each phase: run the full test suite, update this brief with ✅/❌ status per definition-of-done, and only proceed on explicit instruction.
- Keep the `IDownloadClient` and indexer client interfaces stable once Phase 3 lands — new clients are additive only.
- Prefer explicit, typed Pydantic models over dicts at all system boundaries.
