"""Hardened XML parsing for indexer responses (untrusted input: no entities, no DTDs)."""

from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring


class IndexerResponseError(Exception):
    """The indexer answered, but not with something we can use."""


def parse_xml(content: bytes) -> Element:
    try:
        return fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as exc:
        raise IndexerResponseError(f"Indexer returned invalid XML: {exc}") from exc


def local_name(tag: str) -> str:
    """'{namespace}attr' -> 'attr'."""
    return tag.rsplit("}", 1)[-1]


def raise_for_error(root: Element) -> None:
    """Newznab reports problems as <error code="100" description="..."/> with HTTP 200."""
    if local_name(root.tag) == "error":
        code = root.get("code", "?")
        description = root.get("description") or "Unknown error"
        raise IndexerResponseError(f"Indexer error {code}: {description}")
