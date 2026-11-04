# Importing

When a download finishes, Magarr finds the magazine files in it (skipping samples and junk such
as `.nfo` files), works out which issue each belongs to, and files them under your naming scheme.

- **Usenet** downloads are **moved** by default; afterwards the leftover folder is deleted if only
  junk remains, and the item is removed from the download client's history.
- **Torrents** are **hard-linked** by default (copied if the library is on another filesystem),
  so they keep seeding.
- Both can be set to move, copy or hard link in Settings → Media Management → *Importing*.

A download can fill several issues (a pack), and a file named for a different issue goes to that
issue. Where a download contains several formats of one issue, the best by your profile wins.

## Upgrades

If an issue already has a file, the new one replaces it only if it's better by the profile. The
old file goes to the **recycle bin** if one is set, otherwise it's deleted; it's only removed once
the new file is in place.

## Permissions

Settings → Media Management → *Importing* can set file and folder modes (`664`, `775`) and an
owner for imported files. Leave them blank to keep the defaults.

## When the download folder is read-only

If the download client's files may be read but not moved or deleted (common with SABnzbd on a
NAS), Magarr imports a **copy** and leaves the original; the queue explains how to let Magarr
move files instead (see [Download clients](download-clients.md#usenet-download-folder-permissions)).
If a file is briefly locked because the client is still finishing with it, Magarr retries for ten
minutes before reporting a problem.

## Manual import

Activity → *Manual Import* scans any folder (or a download that couldn't be imported), suggests
the issue for each file, and imports the ones you confirm. Only plain magazine files given by
their full path are accepted; a file that's already another issue's file is refused.
