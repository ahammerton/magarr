"""Parse magazine file names into a title plus issue identifiers.

Handles the numbering schemes in §4.2 of the brief, e.g.::

    National Geographic - 2014-07 - Issue 045.pdf
    Magazine.Name.2024.05.pdf
    MagName.Issue.128.May.2024.pdf
    MagName.Vol12.No3.2024.pdf
    MagName.Special.Collectors.Edition.2024.pdf
    MagName 2024 Week 19.pdf / MagName.2024-W19.pdf
    MagName - May-June 2024.pdf
    2510 MagName.pdf            (YYMM prefix: October 2025)
    2413 MagName Christmas.pdf  (month 13: the year's extra issue, a special)
    MagName94-Dec91.pdf         (glued; retried with symbols as spaces: issue 94, Dec 1991)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import PurePath

from magarr.domain.enums import EXTENSION_FORMATS, FileFormat
from magarr.domain.qualities import quality_for_format

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9,
    "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}  # fmt: skip
_MONTH = r"(?P<{name}>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b"
_YEAR = r"(?P<{name}>(?:19|20)\d{{2}})"

# Release/scan noise that is not part of the title or issue.
_NOISE = re.compile(
    r"\b(true\s?pdf|hq|hi-?res|retail|digital|scan(?:ned)?|ebook|e-?mag|pdf|epub|cbz|cbr)\b",
    re.IGNORECASE,
)
# Bracketed tags are dropped, but bracketed dates ("[2023.12.23]") are kept.
_BRACKETS = re.compile(r"[\[{]([^\]}]*)[\]}]")
_MONTH_ANY = "(?:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\b"
_DASH = r"\s*[-\u2013]\s*"


def _y(name: str) -> str:
    return _YEAR.format(name=name)


def _m(name: str) -> str:
    return _MONTH.format(name=name)


# Order matters: more specific shapes first. Each match claims its text, and the earliest
# match marks where the title ends.
# fmt: off
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_ORD = r"(?:st|nd|rd|th)?"
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("vol_no", re.compile(
        r"\bvol(?:ume)?\.?\s*(?P<vol>\d+)\s*[,-]?\s*(?:no|nr|num|number|issue|#)\.?\s*(?P<num>\d+)\b",
        re.IGNORECASE)),
    ("full_date", re.compile(
        rf"\b{_y('y')}[-. ](?P<m>0[1-9]|1[0-2])[-. ](?P<d>0[1-9]|[12]\d|3[01])\b")),
    # Explicit issue/volume numbers come before day patterns: "issue 31 - March 2015" is
    # issue 31, not 31 March. A year followed by a date continuation ("Issue 2024-05") is a date.
    ("issue_no", re.compile(
        r"(?:\b(?:issue|iss|no|nr|num|number|prog)\.?\s*|#\s*)"
        r"(?P<num>(?!(?:19|20)\d{2}[-.]?(?:\d|[qw]\d))\d+)\b",
        re.IGNORECASE)),
    ("dashed_number", re.compile(r"(?<=\s)-\s(?P<num>\d{1,4})\s-(?=\s)")),  # "Edge - 05 - 2013-11"
    ("vol", re.compile(r"\bvol(?:ume)?\.?\s*(?P<vol>\d+)\b", re.IGNORECASE)),
    ("n_number", re.compile(r"\bN\.?\s?(?P<num>\d{2,})\b")),  # French style: "N4690", "N 205"
    # Weekly ranges across months start on the first day:
    # "20 December - 02 January 2025", "January 4th - January 10th 2025"
    ("day_month_range", re.compile(
        rf"\b(?P<d>[0-3]?\d){_ORD}[-. ]+{_m('mn')}{_DASH}"
        rf"[0-3]?\d{_ORD}[-. ]+{_m('mn2')}[-. ,]+{_y('y')}\b",
        re.IGNORECASE)),
    ("month_day_range", re.compile(
        rf"\b{_m('mn')}[-. ]+(?P<d>[0-3]?\d){_ORD}{_DASH}"
        rf"{_m('mn2')}[-. ]+[0-3]?\d{_ORD}[-. ,]+{_y('y')}\b",
        re.IGNORECASE)),
    # "18 May 2024", "2nd March 2024", "25-31 May 2024", "13 19 August 2016"
    ("day_month_name_year", re.compile(
        rf"\b(?P<d>[0-3]?\d){_ORD}(?:(?:{_DASH}|\s+)[0-3]?\d{_ORD})?"
        rf"[-. ]+{_m('mn')}[-. ,]+{_y('y')}\b",
        re.IGNORECASE)),
    # "May 18, 2024", "January 11-17 2025"
    ("month_name_day_year", re.compile(
        rf"\b{_m('mn')}[-. ]+(?P<d>[0-3]?\d){_ORD}(?:{_DASH}[0-3]?\d)?"
        rf"(?:,\s*|[-. ]+){_y('y')}\b",
        re.IGNORECASE)),
    ("week", re.compile(rf"\b{_y('y')}[-. ]?(?:w|wk|week)\s?(?P<w>[0-5]?\d)\b", re.IGNORECASE)),
    ("week_rev", re.compile(rf"\b(?:week|wk)\s?(?P<w>[0-5]?\d)[-. ,]+{_y('y')}\b", re.IGNORECASE)),
    ("quarter", re.compile(rf"\b{_y('y')}[-. ]?q(?P<q>[1-4])\b", re.IGNORECASE)),
    ("quarter_rev", re.compile(rf"\bq(?P<q>[1-4])[-. ]+{_y('y')}\b", re.IGNORECASE)),
    ("year_month", re.compile(rf"\b{_y('y')}[-. ](?P<m>0[1-9]|1[0-2])\b(?![-. ]\d)")),
    # "May 2024", "May-June 2024", "January February 2017", "September-October-November 2026"
    ("month_name_year", re.compile(
        # mn2 captures the last month, for "December-January 2024" (which started in 2023)
        rf"\b{_m('mn')}(?:(?:\s*[-/&]\s*|\s+){_m('mn2')})*[-. ,]*{_y('y')}\b", re.IGNORECASE)),
    ("year_month_name", re.compile(rf"\b{_y('y')}[-. ]+{_m('mn')}", re.IGNORECASE)),
    # Numeric dates without a leading year follow the US order seen on indexers:
    # "11 17 2022", "12 22-29 2022" (MM DD YYYY); a first number over 12 must be the day.
    ("mdy", re.compile(
        rf"\b(?P<m>0?[1-9]|1[0-2])[-. ](?P<d>{_DAY})(?:{_DASH}{_DAY})?[-. ]{_y('y')}\b")),
    ("dmy", re.compile(rf"\b(?P<d>1[3-9]|2\d|3[01])[-. ](?P<m>0?[1-9]|1[0-2])[-. ]{_y('y')}\b")),
    ("month_year_numeric", re.compile(rf"\b(?P<m>0?[1-9]|1[0-2])[-. /]{_y('y')}\b")),  # "03 2025"
    ("special", re.compile(
        r"\b(?P<special>(?:special|collector'?s?|annual|holiday|christmas|xmas|summer|winter|spring|"
        r"autumn|fall)"
        r"\b.*?)(?=[-. ]+(?:19|20)\d{2}\b|$)",
        re.IGNORECASE)),
    ("number_before_year", re.compile(rf"\b(?P<num>\d{{1,4}})\s+{_y('y')}\b")),  # "MAD 033 2023"
    ("year", re.compile(rf"\b{_y('y')}\b")),
    ("trailing_number", re.compile(r"\s(?P<num>\d{1,4})$")),
]
# fmt: on

# "2510 Tamiya Model Magazine": a leading YYMM date, then the title. A valid month is required,
# so titles that start with a number ("2000 AD", "1843 Magazine") are left alone.
# Month 13 is the year's extra issue (a Christmas issue or another special), e.g. "2413 Olive".
_YYMM_PREFIX = re.compile(r"^(?P<yy>\d{2})(?P<m>0[1-9]|1[0-3])(?:\s*-)?\s+(?=[^\W\d_])")
_CHRISTMAS = re.compile(r"\b(?:christmas|xmas)\b", re.IGNORECASE)


def _yymm_year(yy: int) -> int:
    """Two-digit year: up to next year is this century ("25" -> 2025), later ones the last."""
    return 2000 + yy if yy <= date.today().year % 100 + 1 else 1900 + yy


@dataclass
class ParsedIssue:
    title: str
    format: FileFormat | None = None
    year: int | None = None
    month: int | None = None
    day: int | None = None
    week: int | None = None
    quarter: int | None = None
    volume: int | None = None
    number: str | None = None
    special: str | None = None
    # From a "month 13" prefix: a special whose name depends on the magazine (see
    # magarr.importers.matching.specialise), dated December.
    thirteenth: bool = False

    @property
    def issue_key(self) -> str | None:
        """Issue number to use when this file creates a new issue record."""
        if self.volume is not None and self.number:
            return f"Vol {self.volume} No {self.number}"
        if self.volume is not None and not (self.month or self.week or self.quarter):
            return f"Vol {self.volume}"
        if self.number:
            return self.number
        if self.special:
            return f"{self.special} {self.year}" if self.year else self.special
        if self.year and self.week:
            return f"{self.year}-W{self.week:02d}"
        if self.year and self.quarter:
            return f"{self.year}-Q{self.quarter}"
        if self.year and self.month and self.day:
            return f"{self.year}-{self.month:02d}-{self.day:02d}"
        if self.year and self.month:
            return f"{self.year}-{self.month:02d}"
        if self.year:
            return str(self.year)
        return None

    @property
    def publish_date(self) -> date | None:
        if not self.year:
            return None
        if self.week:
            try:
                return date.fromisocalendar(self.year, self.week, 1)
            except ValueError:
                return None
        month = self.month or ((self.quarter - 1) * 3 + 1 if self.quarter else 1)
        try:
            return date(self.year, month, self.day or 1)
        except ValueError:
            return None


def _normalize(stem: str) -> str:
    text = _BRACKETS.sub(lambda m: f" {m[1]} " if re.search(r"\d", m[1]) else " ", stem)
    text = re.sub(r"[_.]", " ", text)
    text = re.sub(r"[()]", " ", text)
    text = _NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_title(text: str) -> str:
    text = text.strip().strip(" -,#&")  # trailing separators first, so "issue -" is caught
    text = re.sub(r"\b(?:issue|iss|no|nr|vol(?:ume)?)\.?\s*$", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -,#&")


def _strip_number(value: str) -> str:
    return value.lstrip("0") or "0"


# Loose retry for file names the normal parse can't place: "SinclairUser030-Sep84",
# "Big-K-Issue-02", "15 - The Weathering Magazine".
_MONTH_WORD = "|".join(sorted(MONTHS, key=len, reverse=True))
_NOT_A_TITLE = (
    rf"(?:{_MONTH_WORD}|issue|iss|no|nr|num|number|vol|volume|prog|annual|special|edition|week|wk)"
)
# A number glued to a title word is its issue number ("Crash94"); not to a month ("Dec91"),
# a label ("Issue877", "Annual1983"), a year (4 digits) or an ordinal ("3rd").
_GLUED_NUMBER = re.compile(
    rf"(?<![A-Za-z])(?!{_NOT_A_TITLE}\d)([A-Za-z]*[a-z])(\d{{1,3}})(?!\d|st|nd|rd|th)", re.I
)
_MONTH_SHORT_YEAR = re.compile(rf"\b({_MONTH_WORD})\s+(\d{{2}})\b", re.I)  # "Dec 91"
_LEADING_NUMBER = re.compile(r"^(?P<num>\d{1,3})\s+(?=[^\W\d_])")  # "15 The Weathering..."


def _loosen(text: str) -> str:
    """Symbols as spaces, glued words and numbers apart, two-digit years after a month."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)  # SinclairUser -> Sinclair User
    text = _GLUED_NUMBER.sub(lambda m: f"{m[1]} Issue {m[2]} ", text)  # Crash94 -> Crash Issue 94
    text = re.sub(r"[-_+~,;!]", " ", text)
    text = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", text)  # Dec91 -> Dec 91, November2023
    text = re.sub(r"(?<=\d)(?=(?!(?:st|nd|rd|th)\b)[A-Za-z])", " ", text)  # 2024TP
    text = _MONTH_SHORT_YEAR.sub(lambda m: f"{m[1]} {_yymm_year(int(m[2]))}", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_filename(name: str) -> ParsedIssue:
    path = PurePath(name)
    fmt = EXTENSION_FORMATS.get(path.suffix.lower())
    text = _normalize(path.stem if fmt else path.name)
    parsed = _parse_text(text, ParsedIssue(title="", format=fmt))
    if parsed.issue_key is not None:
        return parsed
    # Nothing found: try again treating symbols (- _ ...) as spaces and splitting glued text.
    loose = _loosen(text)
    lead = _LEADING_NUMBER.match(loose)
    if loose == text and lead is None:
        return parsed
    retry = _parse_text(loose[lead.end() :] if lead else loose, ParsedIssue(title="", format=fmt))
    if lead and retry.number is None:
        retry.number = _strip_number(lead["num"])
    return retry if retry.issue_key is not None else parsed


def _free_matches(
    pattern: re.Pattern[str], text: str, free: Callable[[re.Match[str]], bool]
) -> list[re.Match[str]]:
    """Matches that don't overlap claimed text, retrying just past any match that does.

    ``finditer`` alone would skip the whole overlapping stretch: in "Volume 7-28 September 2023"
    the day pattern first hits "7-28 September 2023" (7 is claimed) and must retry at "28".
    """
    found, pos = [], 0
    while (match := pattern.search(text, pos)) is not None:
        if free(match):
            found.append(match)
            pos = match.end()
        else:
            pos = match.start() + 1
    return found


def _parse_text[P: ParsedIssue](text: str, parsed: P) -> P:
    """Fill ``parsed`` with title and issue identifiers found in normalized ``text``."""
    year_in_text = True  # False when the only year is a YYMM prefix
    if prefix := _YYMM_PREFIX.match(text):
        # A date written later in the name still wins; this only fills the gaps.
        parsed.year, parsed.month = _yymm_year(int(prefix["yy"])), int(prefix["m"])
        text = text[prefix.end() :]
        year_in_text = False
        if parsed.month == 13:
            # The year's extra issue: sorts after December. Named later (Christmas, a handbook).
            parsed.month, parsed.thirteenth, parsed.special = 12, True, "Special"
    title_end = len(text)
    claimed: list[tuple[int, int]] = []  # text already used by an earlier, more specific pattern

    def free(m: re.Match[str]) -> bool:
        return all(m.end() <= start or m.start() >= end for start, end in claimed)

    for kind, pattern in _PATTERNS:
        candidates = _free_matches(pattern, text, free)
        # A bare year is most likely the last one: "2000 AD - Prog 2380 (2024)".
        match = (candidates[-1] if kind == "year" else candidates[0]) if candidates else None
        if not match:
            continue
        claimed.append(match.span())
        groups = match.groupdict()
        if kind == "trailing_number" and (
            parsed.number or (parsed.year and year_in_text) or parsed.special
        ):
            continue
        if kind in ("year", "year_month", "month_name_year", "year_month_name") and parsed.year:
            # A later, less specific date shape; only fill gaps.
            if parsed.month is None and (groups.get("m") or groups.get("mn")):
                parsed.month = int(groups["m"]) if groups.get("m") else MONTHS[groups["mn"].lower()]
            continue
        if kind == "special" and (parsed.number or parsed.week or parsed.quarter):
            continue

        if groups.get("y"):
            parsed.year = int(groups["y"])
        if groups.get("m"):
            parsed.month = int(groups["m"])
        if groups.get("mn"):
            parsed.month = MONTHS[groups["mn"].lower()]
        if groups.get("d"):
            parsed.day = int(groups["d"])
        if groups.get("w"):
            parsed.week = int(groups["w"])
        if groups.get("q"):
            parsed.quarter = int(groups["q"])
        if groups.get("vol"):
            parsed.volume = int(groups["vol"])
        if groups.get("num") and parsed.number is None:
            parsed.number = _strip_number(groups["num"])
        # Ranges labelled with the later year started the year before:
        # "20 December - 02 January 2025", "December-January 2024".
        if groups.get("mn2") and MONTHS[groups["mn"].lower()] > MONTHS[groups["mn2"].lower()]:
            parsed.year -= 1  # "20 December - 02 January 2025" started in 2024
        if groups.get("special"):
            words = re.sub(r"\s+", " ", groups["special"]).strip(" -").split(" ")
            # Capitalize words without .title(), which would give "12Th".
            special = " ".join(w[:1].upper() + w[1:].lower() for w in words)
            if _CHRISTMAS.search(special):
                # One name for "Xmas", "Christmas" and "Christmas Special" so files and releases
                # of the same issue match.
                special = _CHRISTMAS.sub("Christmas", special)
                if "special" not in special.casefold():
                    special = special.replace("Christmas", "Christmas Special", 1)
                if parsed.month is None:
                    parsed.month = 12  # dated with the December issue it sits next to
            parsed.special = special
        title_end = min(title_end, match.start())

    parsed.title = _clean_title(text[:title_end])
    return parsed


# --- Release titles (indexer results) ---------------------------------------------------------

_FORMAT_TOKENS: dict[str, FileFormat] = {
    "pdf": FileFormat.PDF,
    "epub": FileFormat.EPUB,
    "cbz": FileFormat.CBZ,
    "cbr": FileFormat.CBR,
    "cb7": FileFormat.CB7,
    "mobi": FileFormat.MOBI,
    "azw3": FileFormat.AZW3,
    "djvu": FileFormat.DJVU,
}
# "TruePDF" (glued) still names the format.
_FORMAT_RE = re.compile(
    r"(?<![a-z0-9])(?:true)?(" + "|".join(_FORMAT_TOKENS) + r")(?![a-z0-9])", re.I
)
_HIRES_RE = re.compile(r"\b(hq|hi-?res|high[ .-]?(?:res(?:olution)?|quality)|hd)\b", re.I)
_RELEASE_NOISE = re.compile(
    r"\b(magazi?ne?|ebook|e-book|hybrid|true|retail|digital(?:\s+edition)?|scan(?:ned)?|"
    r"interactive|repack|proper)\b",
    re.I,
)
# Scene-style "...-GROUP" suffix on dotted names with no spaces.
_GROUP_RE = re.compile(r"-([A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*)$")
_REGIONS = {
    "uk": "UK", "us": "US", "usa": "US", "au": "Australia", "australia": "Australia",
    "nz": "New Zealand", "ca": "Canada", "canada": "Canada", "india": "India", "in": "India",
    "za": "South Africa", "sa": "South Africa", "ireland": "Ireland", "ie": "Ireland",
    "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy", "nl": "Netherlands",
    "international": "International", "intl": "International", "asia": "Asia",
    "middle east": "Middle East", "me": "Middle East",
}  # fmt: skip
_REGION_RE = re.compile(
    r"\b(" + "|".join(sorted((re.escape(r) for r in _REGIONS), key=len, reverse=True)) + r")\b"
)
# Scene-style language tags ("SPANiSH", "iTALiAN"); untagged releases are English by convention.
_LANGUAGES = {
    "english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it",
    "dutch": "nl", "polish": "pl", "russian": "ru", "portuguese": "pt", "swedish": "sv",
    "norwegian": "no", "danish": "da", "finnish": "fi", "czech": "cs", "hungarian": "hu",
    "greek": "el", "turkish": "tr", "japanese": "ja", "chinese": "zh", "korean": "ko",
    "arabic": "ar", "hebrew": "he", "hindi": "hi", "romanian": "ro", "ukrainian": "uk",
    "slovak": "sk", "slovenian": "sl", "croatian": "hr", "serbian": "sr", "bulgarian": "bg",
    "indonesian": "id", "thai": "th", "vietnamese": "vi", "catalan": "ca",
}  # fmt: skip
LANGUAGE_NAMES = {code: name.title() for name, code in _LANGUAGES.items()}
_LANGUAGE_RE = re.compile(r"\b(" + "|".join(_LANGUAGES) + r")\b", re.I)

_PACK_RE = re.compile(
    r"\b(complete(?:\s+year)?|full\s+year|bundle|pack|all\s+issues|\d+\s+issues)\b"
    r"|\b(?:19|20)\d{2}\s*[-\u2013]\s*(?:19|20)\d{2}\b"
    # "Issues 300-312" is a pack; "Issue 1589-6 January" is one issue and its date.
    r"|\b(?:issues?|no\.?|#)\s*\d+\s*[-\u2013]\s*\d+\b(?![-. ]+" + _MONTH_ANY + ")",
    re.I,
)


@dataclass
class ParsedRelease(ParsedIssue):
    quality: str = "unknown"
    edition: str | None = None
    group: str | None = None
    is_pack: bool = False
    language: str | None = None  # ISO 639-1, only when the title names one


def parse_release(title: str) -> ParsedRelease:
    """Parse an indexer release title (no file extension; tags, groups and regions)."""
    text = title.strip()
    # A trailing extension (".pdf", or a ".PDF" tag on dotted names) still tells us the format.
    ext_format = EXTENSION_FORMATS.get(PurePath(text).suffix.lower())
    if ext_format:
        text = text[: -len(PurePath(text).suffix)]

    group = None
    if " " not in text and (match := _GROUP_RE.search(text)):
        group = match[1]
        text = text[: match.start()]

    formats = [_FORMAT_TOKENS[m.lower()] for m in _FORMAT_RE.findall(text)]
    if not formats and group and group.lower() in _FORMAT_TOKENS:
        formats = [_FORMAT_TOKENS[group.lower()]]  # "...eBook-PDF" is a format, not a group
        group = None
    fmt = formats[0] if formats else ext_format
    hires = bool(_HIRES_RE.search(text))

    spaced = re.sub(r"[_.]", " ", text)
    region = _REGION_RE.search(spaced.replace("(", " ").replace(")", " ").lower())
    is_pack = bool(_PACK_RE.search(spaced))

    # A language word only counts as a tag after a number or date ("French Country" is a title).
    language = next(
        (m for m in _LANGUAGE_RE.finditer(spaced) if re.search(r"\d", spaced[: m.start()])), None
    )
    if language:
        spaced = spaced[: language.start()] + " " + spaced[language.end() :]
    cleaned = _HIRES_RE.sub(" ", _RELEASE_NOISE.sub(" ", spaced))
    if is_pack:
        cleaned = _PACK_RE.sub(" ", cleaned)
    parsed = _parse_text(_normalize(cleaned), ParsedRelease(title="", format=fmt))
    parsed.group = group
    parsed.is_pack = is_pack
    parsed.edition = _REGIONS[region[1]] if region else None
    parsed.language = _LANGUAGES[language[1].lower()] if language else None
    if fmt is FileFormat.PDF and hires:
        parsed.quality = "pdf_hires"
    elif fmt is not None:
        parsed.quality = quality_for_format(fmt)
    return parsed


def detect_region(text: str) -> str | None:
    """Region/edition named in a title, e.g. 'Wired UK' -> 'UK'."""
    match = _REGION_RE.search(re.sub(r"[_.()]", " ", text).lower())
    return _REGIONS[match[1]] if match else None
