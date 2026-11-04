# Troubleshooting

**Komga (or another reader) shows a series called "2026".** Your naming puts issues in year
folders, and readers treat each folder as a series. Clear the year folder pattern in Settings →
Media Management; new imports then go straight into the magazine's folder.

**"Permission denied" importing from SABnzbd, or the queue says "Imported as a copy".** The
download client's files are read-only to Magarr: see
[Download clients → permissions](download-clients.md#usenet-download-folder-permissions).

**A download waits with "Magarr can't see …".** The download client and Magarr see the folder
under different paths: mount it at the same path, or add a
[remote path mapping](download-clients.md#remote-path-mappings).

**Files stay under Unmapped Files.** The reason is shown for each. "Could not determine the issue"
means the name has no number or date Magarr recognises (see
[file names](library.md#file-names-magarr-understands)); renaming the file or adding the issue by
hand and scanning again fixes it. "Already has a file" usually means a duplicate.

**An indexer isn't being searched.** After three failures in a row it's skipped for a while
(System → Health shows until when). Check it with *Test* in Settings → Indexers.

**Nothing is being grabbed.** Check that automation isn't paused (Settings → Automation), the
magazine and the issue are monitored, the issue is in the past or the next week, and the search
window's rejection reasons for the issue.

**macOS with Colima: Magarr can't reach devices on the LAN.** Colima's default VM network
(`192.168.5.0/24`) can clash with home networks. Change `network.gatewayAddress` in
`~/.colima/default/colima.yaml`, and share any folder outside your home directory with the VM
(`mounts:` with full paths).
