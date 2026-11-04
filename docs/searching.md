# Indexers and searching

## Indexers

The easiest way is **Prowlarr**: Settings → Indexers → enter Prowlarr's URL and API key → *Sync
indexers*. Magarr adds one indexer per enabled Prowlarr indexer that has book or magazine
categories, and
syncs again when you ask. Newznab (Usenet) and Torznab (BitTorrent) indexers can also be added by
hand.

Per indexer: categories to search, priority (lower first when releases are otherwise equal), a
minimum interval between requests (Magarr never asks faster, even with RSS sync, the backlog
search and your own searches running together), and optional tags (an indexer with tags only
serves magazines with one of them).

An indexer that fails three times in a row is skipped for 5 minutes, then 15, 30, an hour and
so on up to a day; a success resets it. The Health page lists failing indexers.

## Quality profiles

A profile (Settings → Profiles) lists qualities in order of preference (PDF hi-res, PDF, EPUB,
CBZ...), which are allowed, a size limit per quality, and where upgrading stops. It can also
restrict protocols and require or forbid words in release names (`True PDF`, or a `/regex/`).

## The decision rules

Every release is checked, and the search window shows why it was rejected:

1. it's this magazine (title or alternate title, fuzzy), the right edition and language;
2. it's this issue (number, date, week, quarter, special) and not a multi-issue pack (packs can be
   grabbed by hand: every issue in them is imported);
3. the quality is allowed, within its size limit, on an allowed protocol;
4. required words present, forbidden words absent;
5. not blocklisted after a failed download, not already downloading;
6. an upgrade over the existing file, below the cutoff.

Accepted releases are ranked by quality, then seeders, then age, then indexer priority.

## Searching and grabbing by hand

The search icon on an issue searches every indexer. *Grab* sends the release to the best enabled
download client for its protocol; a rejected release can still be grabbed after a confirmation.
