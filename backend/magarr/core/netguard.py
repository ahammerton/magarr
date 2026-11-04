"""SSRF guard: which addresses Magarr may be pointed at.

Two levels, because a home server's own services live on the LAN:

* **Configured** URLs (indexers, Prowlarr, download clients, notifications) are the user's own
  choice, so private and loopback addresses are fine. Never allowed: link-local (including the
  169.254.169.254 cloud metadata service), multicast and unspecified addresses, or schemes other
  than http(s).
* **Fetched** URLs that arrive in untrusted content (release download links in indexer feeds,
  and every redirect they lead to) must point at the public internet or at the indexer's own
  host. A hostile feed can't send Magarr to the router's admin page or another LAN service.

Names are resolved and every address checked. (A DNS answer that changes between this check and
the request, "DNS rebinding", isn't covered; the indexer-host allowance keeps that window small.)
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from magarr.domain.errors import DomainError

Address = ipaddress.IPv4Address | ipaddress.IPv6Address

_METADATA = {ipaddress.ip_address("fd00:ec2::254")}  # AWS's IPv6 metadata endpoint


class UnsafeUrlError(DomainError):
    pass


def _never(address: Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or address in _METADATA
    )


def _internal(address: Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return not address.is_global


def _split(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeUrlError("Only http:// and https:// URLs can be used")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError(f"Invalid port in {url}") from exc
    return parts.hostname, port


def _literal(host: str) -> Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def lookup(host: str, port: int) -> set[Address]:
    """DNS lookup (tests replace this: they never touch real DNS). Raises OSError."""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return {ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in infos}


def check_configured_url(url: str) -> None:
    """For URLs the user typed in. Names that don't resolve (yet) are allowed."""
    host, port = _split(url)
    literal = _literal(host)
    if literal is not None:
        addresses = {literal}
    else:
        try:
            addresses = lookup(host, port)
        except OSError:
            return  # e.g. a container name that resolves only once that container runs
    if bad := sorted(str(a) for a in addresses if _never(a)):
        raise UnsafeUrlError(f"{host} resolves to {', '.join(bad)}, which Magarr won't connect to")


async def resolve(host: str, port: int) -> set[Address]:
    literal = _literal(host)
    if literal is not None:
        return {literal}
    try:
        return await asyncio.to_thread(lookup, host, port)
    except OSError:
        return set()  # unresolvable: the request itself will fail; nothing to connect to


async def check_fetched_url(url: str, trusted_hosts: set[Address]) -> None:
    """For URLs from indexer responses. ``trusted_hosts``: the indexer's own addresses."""
    host, port = _split(url)
    addresses = await resolve(host, port)
    for address in addresses:
        if _never(address):
            raise UnsafeUrlError(f"The release link points at {address}; refusing it")
        if _internal(address) and address not in trusted_hosts:
            raise UnsafeUrlError(
                f"The release link points into your network ({host}); only the indexer's own "
                "address is allowed for that"
            )


async def trusted_addresses(*urls: str) -> set[Address]:
    """Addresses of hosts the user configured (an indexer and, for Prowlarr, its host)."""
    found: set[Address] = set()
    for url in urls:
        try:
            found |= await resolve(*_split(url))
        except UnsafeUrlError:
            continue
    return found
