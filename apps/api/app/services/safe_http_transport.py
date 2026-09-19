"""Dial validated public IPs while preserving HTTP Host and TLS hostname verification."""

import httpx

from apps.api.app.services.crawler_security import resolve_public_http_url


class PublicNetworkTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        # Disable connection reuse: two hosts sharing an IP must not share TLS
        # identity via a pool keyed by the pinned destination. No environment proxy.
        self._transport = transport or httpx.AsyncHTTPTransport(
            limits=httpx.Limits(max_keepalive_connections=0),
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        addresses = await resolve_public_http_url(str(request.url))
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": request.url.host},
        )
        return await self._transport.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._transport.aclose()
