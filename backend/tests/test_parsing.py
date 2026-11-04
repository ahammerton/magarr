"""Frozen corpus of file names. Add a case whenever a real name is misparsed."""

import pytest

from magarr.domain.enums import FileFormat
from magarr.importers.parsing import parse_filename

# (file name, title, issue_key, publish_date ISO or None)
CORPUS = [
    # Magarr's own default naming
    ("National Geographic - 2014-07 - Issue 045.pdf", "National Geographic", "45", "2014-07-01"),
    (
        "National Geographic - 2024-05 - Issue 2024-05.pdf",
        "National Geographic",
        "2024-05",
        "2024-05-01",
    ),
    (
        "The Economist - 2024-05-11 - Issue 2024-05-11.pdf",
        "The Economist",
        "2024-05-11",
        "2024-05-11",
    ),
    ("Wired - 2024-Q2.pdf", "Wired", "2024-Q2", "2024-04-01"),
    # Dotted year.month
    ("Magazine.Name.2024.05.pdf", "Magazine Name", "2024-05", "2024-05-01"),
    ("PC.Gamer.UK.2023.12.pdf", "PC Gamer UK", "2023-12", "2023-12-01"),
    ("Wired_2024-05.epub", "Wired", "2024-05", "2024-05-01"),
    ("Wired 2024 05.cbz", "Wired", "2024-05", "2024-05-01"),
    # Issue numbers with month names
    ("MagName.Issue.128.May.2024.pdf", "MagName", "128", "2024-05-01"),
    ("Edge.Issue.395.April.2024.pdf", "Edge", "395", "2024-04-01"),
    ("Retro Gamer No.256 (2024).pdf", "Retro Gamer", "256", "2024-01-01"),
    ("Linux Format #312 - February 2024.pdf", "Linux Format", "312", "2024-02-01"),
    ("2600 Magazine - Issue 041.pdf", "2600 Magazine", "41", None),
    ("MagPi Issue 140.pdf", "MagPi", "140", None),
    ("Total Film Nr 345.pdf", "Total Film", "345", None),
    # Volume / number
    ("MagName.Vol12.No3.2024.pdf", "MagName", "Vol 12 No 3", "2024-01-01"),
    (
        "Scientific American Volume 330 Number 5 May 2024.pdf",
        "Scientific American",
        "Vol 330 No 5",
        "2024-05-01",
    ),
    ("Byte Vol. 9, No. 8 (1984).pdf", "Byte", "Vol 9 No 8", "1984-01-01"),
    # Specials
    (
        "MagName.Special.Collectors.Edition.2024.pdf",
        "MagName",
        "Special Collectors Edition 2024",
        "2024-01-01",
    ),
    ("Empire Annual 2023.pdf", "Empire", "Annual 2023", "2023-01-01"),
    (
        "Retro Gamer Collection Summer Special 2022.pdf",
        "Retro Gamer Collection",
        "Summer Special 2022",
        "2022-01-01",
    ),
    # Month name forms
    ("MagName - May 2024.pdf", "MagName", "2024-05", "2024-05-01"),
    ("Vogue.UK.September.2023.True.PDF.pdf", "Vogue UK", "2023-09", "2023-09-01"),
    ("Wallpaper - May-June 2024.pdf", "Wallpaper", "2024-05", "2024-05-01"),
    ("Monocle Jul-Aug 2023.pdf", "Monocle", "2023-07", "2023-07-01"),
    ("Kerrang 2024 March.pdf", "Kerrang", "2024-03", "2024-03-01"),
    ("Mojo Dec 2023.epub", "Mojo", "2023-12", "2023-12-01"),
    # Full dates and weeks
    ("The.Economist.2024.05.11.pdf", "The Economist", "2024-05-11", "2024-05-11"),
    ("New Scientist 2024-03-02.pdf", "New Scientist", "2024-03-02", "2024-03-02"),
    ("MagName 2024 Week 19.pdf", "MagName", "2024-W19", "2024-05-06"),
    ("Autosport.2024.W07.pdf", "Autosport", "2024-W07", "2024-02-12"),
    ("Autosport Week 7, 2024.pdf", "Autosport", "2024-W07", "2024-02-12"),
    # Quarters and bare years
    ("Lapham's Quarterly Q3 2023.pdf", "Lapham's Quarterly", "2023-Q3", "2023-07-01"),
    ("Wisden 2024.pdf", "Wisden", "2024", "2024-01-01"),
    # Noise and brackets
    ("[mag] T3.UK.Issue.358.2024.HQ.PDF.pdf", "T3 UK", "358", "2024-01-01"),
    ("Stuff (2024-02) {retail}.pdf", "Stuff", "2024-02", "2024-02-01"),
    ("Car_Magazine_2024_06_True_PDF.pdf", "Car Magazine", "2024-06", "2024-06-01"),
    # Trailing bare number
    ("PC Gamer 389.pdf", "PC Gamer", "389", None),
    # Leading YYMM date
    ("2510 Tamiya Model Magazine.pdf", "Tamiya Model Magazine", "2025-10", "2025-10-01"),
    (
        "1703 Tamiya Model Magazine International.pdf",
        "Tamiya Model Magazine International",
        "2017-03",
        "2017-03-01",
    ),
    ("2501 - Tamiya Model Magazine.pdf", "Tamiya Model Magazine", "2025-01", "2025-01-01"),
    ("9905_Edge.pdf", "Edge", "1999-05", "1999-05-01"),
    ("2510 Tamiya Model Magazine 360.pdf", "Tamiya Model Magazine", "360", "2025-10-01"),
    # ...but not titles that start with a number
    ("2000 AD - Prog 2380 (2024).pdf", "2000 AD", "2380", "2024-01-01"),
    ("1843 Magazine 2024-05.pdf", "1843 Magazine", "2024-05", "2024-05-01"),
    # Glued or dash-separated names (retried with symbols as spaces); real library names
    ("Crash04-May84.pdf", "Crash", "4", "1984-05-01"),
    ("Crash94-Dec91.pdf", "Crash", "94", "1991-12-01"),
    ("SinclairUser030-Sep84.pdf", "Sinclair User", "30", "1984-09-01"),
    ("YourSinclair57-Sep90.pdf", "Your Sinclair", "57", "1990-09-01"),
    ("SinclairUser-Annual1983.pdf", "Sinclair User", "Annual 1983", "1983-01-01"),
    ("Big-K-Issue-02.pdf", "Big K", "2", None),
    ("15 - The Weathering Magazine.pdf", "The Weathering Magazine", "15", None),
    ("01 Model Car Truck Motorcycles World.pdf", "Model Car Truck Motorcycles World", "1", None),
    ("SFX_June24.pdf", "SFX", "2024-06", "2024-06-01"),
    ("ModelRailNovember2023.pdf", "Model Rail", "2023-11", "2023-11-01"),
    ("RailwayModellerIssue877November2023.pdf", "Railway Modeller", "877", "2023-11-01"),
    ("Olive_Magazine_-_January2024.pdf", "Olive Magazine", "2024-01", "2024-01-01"),
    ("HCC133_ALL_PAGES_optimised.pdf", "HCC", "133", None),
    # Specials: month 13 is the year's extra issue; Christmas issues sit with December
    ("2413 Olive Christmas.pdf", "Olive", "Christmas Special 2024", "2024-12-01"),
    ("2413_APC.pdf", "APC", "Special 2024", "2024-12-01"),
    ("Viz Xmas Special 2026.pdf", "Viz", "Christmas Special 2026", "2026-12-01"),
    ("Viz Christmas 2026.pdf", "Viz", "Christmas Special 2026", "2026-12-01"),
    # Nothing usable
    ("cover.pdf", "cover", None, None),
]


@pytest.mark.parametrize(("name", "title", "key", "published"), CORPUS)
def test_corpus(name: str, title: str, key: str | None, published: str | None) -> None:
    parsed = parse_filename(name)
    assert parsed.title == title
    assert parsed.issue_key == key
    assert (parsed.publish_date.isoformat() if parsed.publish_date else None) == published


@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("a 2024-01.pdf", FileFormat.PDF),
        ("a 2024-01.EPUB", FileFormat.EPUB),
        ("a 2024-01.cbr", FileFormat.CBR),
        ("a 2024-01.txt", None),
    ],
)
def test_format_from_extension(name: str, fmt: FileFormat | None) -> None:
    assert parse_filename(name).format is fmt


def test_issue_number_followed_by_date_key_is_not_a_number() -> None:
    parsed = parse_filename("Wired - Issue 2024-Q2.pdf")
    assert parsed.number is None
    assert parsed.issue_key == "2024-Q2"


@pytest.mark.parametrize(
    ("name", "magazine", "key"),
    [
        ("2513 Fine Scale Modeler Ship Handbook.pdf", "Fine Scale Modeler", "Ship Handbook 2025"),
        ("2413 Fine Scale Modeler.pdf", "Fine Scale Modeler", "Special 2024"),
        ("2313 BBC Good Food UK.pdf", "BBC Good Food", "Special 2023"),  # a region isn't a name
        ("2413 Olive Christmas.pdf", "Olive Magazine", "Christmas Special 2024"),
        ("2412 Olive.pdf", "Olive Magazine", "2024-12"),  # a regular December issue
    ],
)
def test_month_13_specials_are_named_from_what_the_file_adds(name, magazine, key) -> None:
    from magarr.domain.models import Magazine
    from magarr.importers.matching import specialise

    mag = Magazine(title=magazine, folder=magazine, alternate_titles=[])
    assert specialise(parse_filename(name), mag).issue_key == key


def test_files_and_releases_of_a_christmas_special_agree() -> None:
    from magarr.importers.parsing import parse_release

    file_key = parse_filename("Viz - Xmas 2026.pdf").issue_key
    assert file_key == parse_release("Viz.Christmas.Special.2026.HYBRiD.MAGAZiNE").issue_key
