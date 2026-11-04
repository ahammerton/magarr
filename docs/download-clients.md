# Download clients

Settings → Download Clients. Each client has a category (or label) for Magarr's downloads,
**magazines** by default. Use *Test* after saving: it also warns about a missing category.
When several clients handle the same protocol, the lowest priority number is used.

| Client | Protocol | Notes |
|---|---|---|
| SABnzbd | Usenet | API key from SABnzbd's Config → General. Create the category in SABnzbd. |
| NZBGet | Usenet | Username and password of NZBGet's control user. |
| qBittorrent | BitTorrent | Web UI username and password; the category is created if missing. |
| Transmission | BitTorrent | RPC username/password if set; the category becomes a label (Transmission 3.0+). Set *Directory* to put downloads in a specific folder. |
| Deluge | BitTorrent | Web UI password (`deluge` by default). The category needs Deluge's **Label** plugin; Magarr warns if it's off. |
| rTorrent | BitTorrent | The XML-RPC endpoint, usually ruTorrent's `/RPC2`. The category goes in rTorrent's label (`d.custom1`). |

## Remote path mappings

Download clients report where they put files *as they see it*. If Magarr sees the same folder
under a different path (another machine, another container), add a mapping on the same page:
client host, the client's path, Magarr's path. Example: SABnzbd reports
`/data/usenet/complete`, which Magarr has mounted at `/downloads/complete`.

Until a mapping exists, such downloads wait in Activity → Queue with a hint, and are imported
automatically once you add it.

## Failed downloads

A failed download is blocklisted (that release isn't tried again for that issue) and, if
*Redownload failed* is on, the next-best release is grabbed: at most *Automatic retries per issue*
times (3 by default), then Magarr waits for you.

## Usenet download folder permissions

SABnzbd and NZBGet write files as their own user. If Magarr isn't allowed to rename or delete
them, it imports copies instead and says so in the queue. To let Magarr move them, set SABnzbd's
**Config → Folders → Permissions for completed downloads** to `777` (or a group both share), or
NZBGet's **UMask** to `000`.
