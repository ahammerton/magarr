"""Newznab/Torznab category ids relevant to periodicals (the 7000 'Books' range)."""

BOOKS = 7000
MAGAZINES = 7010
EBOOKS = 7020
COMICS = 7030

CATEGORY_NAMES: dict[int, str] = {
    7000: "Books",
    7010: "Books/Mags",
    7020: "Books/EBook",
    7030: "Books/Comics",
    7040: "Books/Technical",
    7050: "Books/Other",
    7060: "Books/Foreign",
}

DEFAULT_CATEGORIES: list[int] = [MAGAZINES]


def is_book_category(category: int) -> bool:
    return 7000 <= category < 8000


def default_categories_for(supported: set[int]) -> list[int]:
    """Best categories to query given what an indexer supports."""
    if MAGAZINES in supported:
        return [MAGAZINES]
    if BOOKS in supported:
        return [BOOKS]
    return sorted(c for c in supported if is_book_category(c)) or list(DEFAULT_CATEGORIES)
