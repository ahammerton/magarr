"""Build small .torrent files for tests."""

import hashlib


def bencode(value) -> bytes:
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, str):
        return bencode(value.encode())
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
        return b"d" + b"".join(bencode(k) + bencode(v) for k, v in items) + b"e"
    raise TypeError(type(value))


def make_torrent(name: str, content: bytes, piece_length: int = 16384) -> tuple[bytes, str]:
    """(torrent bytes, expected info hash) for a single-file torrent of ``content``."""
    pieces = b"".join(
        hashlib.sha1(content[i : i + piece_length], usedforsecurity=False).digest()
        for i in range(0, max(len(content), 1), piece_length)
    )
    info = {"name": name, "length": len(content), "piece length": piece_length, "pieces": pieces}
    torrent = bencode(
        {"announce": "http://tracker.invalid/announce", "info": info, "comment": "test"}
    )
    return torrent, hashlib.sha1(bencode(info), usedforsecurity=False).hexdigest()
