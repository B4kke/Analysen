import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


class UnsafeUrl(ValueError):
    pass


def _public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def validate_public_http_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrl("only http/https are allowed")
    if not parts.hostname:
        raise UnsafeUrl("hostname required")
    host = parts.hostname.casefold()
    if host == "localhost" or host.endswith(".local"):
        raise UnsafeUrl("local hostnames are blocked")

    def resolve() -> list[tuple]:
        return socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)

    records = await asyncio.to_thread(resolve)
    addresses = {record[4][0] for record in records}
    if not addresses or any(not _public_ip(address) for address in addresses):
        raise UnsafeUrl("hostname resolves to a non-public address")
