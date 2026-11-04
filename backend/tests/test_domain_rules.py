from datetime import date

import pytest

from magarr.domain.enums import Frequency, IssueStatus
from magarr.domain.issues import compute_sort_index, expected_issue_slots, resolve_status
from magarr.domain.models import Issue, IssueFile


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("128", 128.0),
        ("12.5", 12.5),
        ("2024-05", 20240500.0),
        ("2024-05-11", 20240511.0),
        ("2024-Q3", 20240701.0),
        ("2024-W19", 20240019.0),
        ("Vol 12 No 3", 12003.0),
    ],
)
def test_sort_index(number: str, expected: float) -> None:
    assert compute_sort_index(number) == expected


def test_sort_index_falls_back_to_publish_date() -> None:
    assert compute_sort_index("Special Edition", date(2024, 6, 15)) == 20240615.0
    assert compute_sort_index("Special Edition") == 0.0


def test_monthly_slots_clamp_day_and_roll_year() -> None:
    slots = expected_issue_slots(Frequency.MONTHLY, date(2024, 11, 30), 4)
    assert slots == [
        ("2024-11", date(2024, 11, 30)),
        ("2024-12", date(2024, 12, 30)),
        ("2025-01", date(2025, 1, 30)),
        ("2025-02", date(2025, 2, 28)),
    ]


def test_weekly_and_quarterly_slots() -> None:
    weekly = expected_issue_slots(Frequency.WEEKLY, date(2024, 12, 25), 2)
    assert weekly == [("2024-12-25", date(2024, 12, 25)), ("2025-01-01", date(2025, 1, 1))]
    quarterly = expected_issue_slots(Frequency.QUARTERLY, date(2024, 1, 1), 3)
    assert [n for n, _ in quarterly] == ["2024-Q1", "2024-Q2", "2024-Q3"]


def test_ad_hoc_has_no_slots() -> None:
    with pytest.raises(ValueError, match="Ad-hoc"):
        expected_issue_slots(Frequency.AD_HOC, date(2024, 1, 1), 1)


def _issue(**kwargs: object) -> Issue:
    issue = Issue(issue_number="1", monitored=False, status=IssueStatus.MISSING, **kwargs)
    issue.file = None
    return issue


def test_status_transitions() -> None:
    issue = _issue()
    resolve_status(issue, IssueStatus.WANTED)
    assert (issue.monitored, issue.status) == (True, IssueStatus.WANTED)

    resolve_status(issue, IssueStatus.IGNORED)
    assert (issue.monitored, issue.status) == (False, IssueStatus.IGNORED)
    resolve_status(issue)  # ignored sticks
    assert issue.status == IssueStatus.IGNORED

    issue.monitored = True  # monitoring again clears ignored
    resolve_status(issue)
    assert issue.status == IssueStatus.WANTED

    resolve_status(issue, IssueStatus.MISSING)
    assert (issue.monitored, issue.status) == (False, IssueStatus.MISSING)


def test_file_means_downloaded_regardless() -> None:
    issue = _issue()
    issue.file = IssueFile(relative_path="a.pdf", size=1, format="pdf", quality="pdf")
    resolve_status(issue, IssueStatus.IGNORED)
    assert issue.status == IssueStatus.DOWNLOADED
