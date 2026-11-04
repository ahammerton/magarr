# Getting started

From a fresh install to Magarr finding new issues by itself.

1. **Root folder.** Settings → Media Management → *Root folders*: add the library folder as Magarr
   sees it, e.g. `/magazines`.
2. **Naming.** On the same page, check the folder and file naming. By default each magazine gets a
   folder named after it and each issue a file like
   `National Geographic - 2026-10 - Issue 2026-10.pdf`. Year sub-folders are optional (readers
   such as Komga treat each folder as a series, so most people leave them off).
3. **Existing magazines.** Library → *Scan library*. Folders become magazines (unmonitored), files
   become issues. Anything Magarr can't place is listed under Library → *Unmapped Files* with the
   reason; see [The library](library.md#file-names-magarr-understands).
4. **Indexers.** Settings → Indexers: enter your Prowlarr URL and API key and *Sync indexers*, or
   add Newznab/Torznab indexers by hand. See [Indexers and searching](searching.md).
5. **Download client.** Settings → Download Clients: add yours and press *Test*. See
   [Download clients](download-clients.md) for each client's notes.
6. **A magazine to follow.** Library → *Add New*, or open one the scan created and *Edit* it: set
   its frequency (monthly, weekly...), and turn on **Monitored**.
7. **Its issues.** Make sure the latest issue is in the list (scan, *Add issue*, or *Generate
   issues*). Magarr adds upcoming issues itself from then on and marks them wanted.
8. **Try a search.** On an issue, the search icon shows what your indexers have, why each release
   is accepted or rejected, and lets you grab one.
9. **Automation.** Settings → Automation: switch on *Automatic searching and grabbing*. RSS sync
   now picks up new releases every 15 minutes, and the backlog search works through older wanted
   issues.
10. **Notifications** (optional). Settings → Notifications: add Discord, Slack, ntfy, Pushover or a
    webhook to hear about grabs and imports.

Press `?` anywhere for keyboard shortcuts.
