# System

## Health

Checked every 15 minutes (or *Check now*): root folders missing, unwritable or low on space;
indexers failing; download clients unreachable; downloads that couldn't be imported or are in a
folder Magarr can't see; failing notifications; automation paused. New problems are sent to
notifications that have the *Health problem* event, and their count shows in the sidebar.

## Tasks

Every scheduled job with its schedule, last result, next run and history: check downloads, add
upcoming issues, RSS sync, backlog search, health check and backup. *Run now* starts one
straight away.

## Backup and restore

A backup is a zip of the database and `config.yaml` in `/config/backups`. One is made every week
and the last 7 kept; *Back up now* makes another. Backups can be downloaded.

**Restore** (a listed backup, or *Restore from file*) checks the backup, keeps a backup of the
current state, and restarts Magarr to swap it in. With Docker's `restart: unless-stopped` Magarr
comes straight back; the page reloads when it does.

## Logs

The live log, filtered by level, plus the log file (`/config/logs/magarr.log`, rotated at 5 MB).
API keys and passwords are masked before anything is written.
