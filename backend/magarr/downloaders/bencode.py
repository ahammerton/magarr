"""Just enough bencode to find a torrent's info hash (qBittorrent identifies torrents by it)."""

from __future__ import annotations

import hashlib


class BencodeError(ValueError):
    pass


def _skip(data: bytes, i: int) -> int:
    """Index just past the bencoded value starting at ``i``."""
    if i >= len(data):
        raise BencodeError("Unexpected end of data")
    lead = data[i : i + 1]
    if lead == b"i":
        end = data.index(b"e", i)
        return end + 1
    if lead in (b"l", b"d"):
        i += 1
        while data[i : i + 1] != b"e":
            i = _skip(data, i)
            if i >= len(data):
                raise BencodeError("Unterminated list or dict")
        return i + 1
    if lead.isdigit():
        colon = data.index(b":", i)
        length = int(data[i:colon])
        end = colon + 1 + length
        if end > len(data):
            raise BencodeError("String runs past the end of the data")
        return end
    raise BencodeError(f"Invalid bencode at byte {i}")


def info_hash(torrent: bytes) -> str:
    """SHA-1 of the raw bencoded ``info`` dictionary, lowercase hex (BitTorrent v1)."""
    if not torrent.startswith(b"d"):
        raise BencodeError("Not a torrent file")
    i = 1
    try:
        while torrent[i : i + 1] != b"e":
            key_end = _skip(torrent, i)
            colon = torrent.index(b":", i)
            key = torrent[colon + 1 : key_end]
            value_end = _skip(torrent, key_end)
            if key == b"info":
                return hashlib.sha1(torrent[key_end:value_end], usedforsecurity=False).hexdigest()
            i = value_end
    except (ValueError, IndexError) as exc:
        raise BencodeError(f"Malformed torrent: {exc}") from exc
    raise BencodeError("Torrent has no info dictionary")


def magnet_hash(magnet: str) -> str | None:
    """Info hash from a magnet link's xt=urn:btih: parameter (hex or base32)."""
    import base64
    from urllib.parse import parse_qs, urlparse

    for xt in parse_qs(urlparse(magnet).query).get("xt", []):
        if xt.lower().startswith("urn:btih:"):
            value = xt[9:]
            if len(value) == 40:
                return value.lower()
            if len(value) == 32:
                return base64.b32decode(value.upper()).hex()
    return None
