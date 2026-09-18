import socket

import httpx
import pytest

from apps.api.app.services import safe_http_transport
from apps.api.app.services.crawler_security import UnsafeUrl, resolve_public_http_url
from apps.api.app.services.safe_http_transport import PublicNetworkTransport


@pytest.mark.asyncio
async def test_transport_pins_destination_preserving_host_and_tls_identity(monkeypatch):
    resolutions = []

    def resolve(host, port, **kwargs):
        resolutions.append(host)
        address = "8.8.8.8" if len(resolutions) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    def wire(request):
        assert request.url.host == "8.8.8.8"
        assert request.headers["host"] == "research.example"
        assert request.extensions["sni_hostname"] == "research.example"
        return httpx.Response(200, text="pinned response")

    async with httpx.AsyncClient(
        transport=PublicNetworkTransport(httpx.MockTransport(wire))
    ) as client:
        response = await client.get("https://research.example/article")
    assert response.text == "pinned response"
    assert str(response.url) == "https://research.example/article"
    assert resolutions == ["research.example"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "224.0.0.1",
        "::ffff:127.0.0.1",
    ],
)
async def test_nonpublic_and_mixed_dns_destinations_are_blocked(monkeypatch, address):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)),
        ],
    )
    with pytest.raises(UnsafeUrl):
        await resolve_public_http_url("http://research.example/")


@pytest.mark.asyncio
async def test_transport_refuses_private_resolution_before_connect(monkeypatch):
    async def reject(url):
        raise UnsafeUrl("DNS destination changed to private")

    monkeypatch.setattr(safe_http_transport, "resolve_public_http_url", reject)
    connected = []
    transport = PublicNetworkTransport(
        httpx.MockTransport(lambda request: connected.append(request))
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UnsafeUrl):
            await client.get("http://research.example/")
    assert connected == []
