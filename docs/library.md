# The library

## Magazines

A magazine has a title (and alternate titles indexers might use), a frequency, a quality
profile, a root folder and a folder inside it. Other settings:

- **Monitored**: Magarr looks for its new and missing issues. Unmonitored magazines are left alone.
- **Only search issues published after**: automatic searches skip older issues.
- **Grab new specials**: RSS sync adds specials it sees (a Christmas special, a handbook) and grabs them.
- **Poster URL**: otherwise the cover of the earliest downloaded issue is used.

Deleting a magazine removes only Magarr's records; files on disk stay. In the table view you can
select several magazines to monitor, unmonitor, change their profile or root folder, or delete
them together. Filters (built in or your own) and sorting are remembered per browser; *My order*
lets you arrange the posters by dragging.

## Issues

An issue's number can be a plain number (`360`), a date (`2026-10`, `2026-10-17`), a week
(`2026-W42`), a quarter (`2026-Q4`), `Vol 3 No 2`, or a special's name (`Christmas Special 2026`).

| Status | Meaning |
|---|---|
| Wanted | monitored, no file: Magarr is looking for it |
| Missing | not monitored, no file |
| Downloaded | has a file |
| Ignored | you've said you don't want it (until you monitor it again) |

When an issue is imported its monitored flag is cleared, so it isn't fetched again even if the
file later disappears.

## Scanning

*Scan library* walks each root folder:

- each folder is matched to a magazine (by folder name, then by title); a folder that matches none
  but holds magazine files becomes a new **unmonitored** magazine (`Viz (1982)` becomes "Viz",
  first published 1982), with its frequency guessed from the issue dates;
- each file is matched to an issue by its name; unknown issues are created (unmonitored);
- files whose recorded issue file has gone are noticed, and the issue goes back to wanted/missing;
- anything that can't be placed is listed under **Unmapped Files** with the reason; the sidebar
  shows how many there are.

Scanning never moves, renames or deletes files.

## File names Magarr understands

Separators can be spaces, dots, dashes or underscores.

| Example | Read as |
|---|---|
| `National Geographic - 2014-07 - Issue 045.pdf` | issue 45, July 2014 |
| `Wired 2024 05.cbz`, `Wired_2024-05.epub` | May 2024 |
| `MagName.Issue.128.May.2024.pdf` | issue 128, May 2024 |
| `MagName.Vol12.No3.2024.pdf` | Vol 12 No 3 |
| `The Economist 18 May 2024.pdf` | 18 May 2024 |
| `MagName 2024 Week 19.pdf` | week 19 of 2024 |
| `Lapham's Quarterly Q3 2023.pdf` | 3rd quarter of 2023 |
| `2510 Tamiya Model Magazine.pdf` | October 2025 (a `YYMM` prefix) |
| `Crash94-Dec91.pdf`, `SinclairUser030-Sep84.pdf` | issue 94, December 1991; issue 30, September 1984 |
| `15 - The Weathering Magazine.pdf` | issue 15 |
| `2413 Olive Christmas.pdf` | Christmas Special 2024 (month 13 is the year's extra issue) |
| `2513 Fine Scale Modeler Ship Handbook.pdf` | Ship Handbook 2025 |
| `Viz Xmas 2026.pdf` | Christmas Special 2026 |

## Specials

Specials are issues of their magazine named "name + year": `Christmas Special 2024`,
`Ship Handbook 2025`, `Annual 1983`, `Special 2024`. Christmas and 13th-month specials are dated
1 December, so they sort after that year's December issue. Specials don't affect the schedule of
regular issues.

For collections of one-off books, make the magazine **ad-hoc**: a file in it with no number or
date becomes an issue named after its title (`The History of Ocean Software`).
