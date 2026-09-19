import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrl(ValueError):
    pass


def _public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


async def resolve_public_http_url(url: str) -> list[str]:
    """Resolve once and return only public destinations that can be pinned at dial time."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrl("only http/https are allowed")
    if not parts.hostname:
        raise UnsafeUrl("hostname required")
    if parts.username or parts.password:
        raise UnsafeUrl("credentialed URLs are blocked")
    host = parts.hostname.casefold()
    if host == "localhost" or host.endswith(".local"):
        raise UnsafeUrl("local hostnames are blocked")

    def resolve() -> list[tuple]:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        return socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)

    records = await asyncio.to_thread(resolve)
    addresses = {record[4][0] for record in records}
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise UnsafeUrl("hostname resolves to a non-public address")
    return sorted(addresses)


async def validate_public_http_url(url: str) -> None:
    await resolve_public_http_url(url)
