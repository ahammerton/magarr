# Automation

Settings → Automation. Only **monitored** magazines and their monitored issues are involved, and
the master switch at the top pauses everything below.

## Upcoming issues

Every hour, Magarr continues each monitored magazine's schedule from its latest regular issue,
in the same numbering (`2026-11`, `2026-W45`, `2026-Q4`, or `361`), and adds the issues due in the
next 45 days (adjustable) as **wanted**, so releases that come out early have an issue to match.
A magazine whose latest issue is more than six periods old is treated as no longer published.

## RSS sync

Every 15 minutes (10 at the least) Magarr reads each indexer's newest releases and grabs the best
acceptable one for any wanted issue. Only releases not seen before are looked at; when nothing is
wanted, indexers aren't asked at all.

## Backlog search

Every hour, a batch of 10 wanted issues is searched on every indexer: issues never searched first,
oldest first, then the least recently searched; each issue at most once a day. It carries on where
it left off after a restart. Issues before a magazine's *Only search issues published after* date
are skipped.

## Wanted and Calendar

**Wanted** lists every wanted issue (or every unmonitored one without a file), with when it was
last searched; select issues to search now or to unmonitor. **Calendar** shows issues by publish
date, colour-coded by status.
