import asyncio

import httpx
import pytest

from apps.api.app.sources.national_library import (
    NationalLibraryAdapter,
    NationalLibraryRestrictedContentError,
)


def _item(*, public_domain: bool, access_allowed_from: str = "EVERYWHERE") -> dict:
    return {
        "id": "URN:NBN:no-nb_digavis_test_20200101_1_1_1",
        "metadata": {
            "title": "Testavisen",
            "creators": ["Utgiver"],
            "mediaTypes": ["aviser"],
            "identifiers": {"urn": "URN:NBN:no-nb_digavis_test_20200101_1_1_1"},
        },
        "accessInfo": {
            "accessAllowedFrom": access_allowed_from,
            "isDigital": True,
            "isPublicDomain": public_domain,
            "license": "publicdomain" if public_domain else "restricted",
            "viewability": "ALL" if public_domain else "RESTRICTED",
        },
        "_links": {
            "self": {
                "href": (
                    "https://api.nb.no/catalog/v1/items/"
                    "URN:NBN:no-nb_digavis_test_20200101_1_1_1"
                )
            }
        },
    }


def test_search_items_builds_full_text_newspaper_query_and_parses_access() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/catalog/v1/items"
        assert request.url.params["q"] == "Eltonåsen"
        assert request.url.params["searchType"] == "FULL_TEXT_SEARCH"
        assert "mediatype:aviser" in request.url.params.get_list("filter")
        assert "digital:Ja" in request.url.params.get_list("filter")
        return httpx.Response(
            200,
            json={"_embedded": {"items": [_item(public_domain=True)]}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NationalLibraryAdapter(client=client)

    result = asyncio.run(
        adapter.search_items(
            "Eltonåsen",
            media_type="aviser",
            digital_only=True,
        )
    )
    asyncio.run(client.aclose())

    assert len(result) == 1
    assert result[0].title == "Testavisen"
    assert result[0].urn.startswith("URN:NBN:")
    assert result[0].access.allows_content_capture() is True


def test_restricted_item_blocks_ocr_fragment_capture() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=_item(public_domain=False))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NationalLibraryAdapter(client=client)

    with pytest.raises(NationalLibraryRestrictedContentError):
        asyncio.run(adapter.content_fragments("restricted-item", "navn"))

    asyncio.run(client.aclose())
    assert len(calls) == 1
    assert not any(path.endswith("/contentfragments") for path in calls)


def test_public_domain_item_returns_clean_content_fragments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contentfragments"):
            assert request.url.params["q"] == '"Maylen Sorkness Andersen"'
            return httpx.Response(
                200,
                json={
                    "contentFragments": [
                        {
                            "pageid": "URN:NBN:no-nb_digavis_test_20200101_1_1_1_1",
                            "text": "før <em>Maylen Sorkness Andersen</em> etter",
                        }
                    ]
                },
            )
        return httpx.Response(200, json=_item(public_domain=True))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = NationalLibraryAdapter(client=client)

    result = asyncio.run(
        adapter.content_fragments(
            "URN:NBN:no-nb_digavis_test_20200101_1_1_1",
            '"Maylen Sorkness Andersen"',
        )
    )
    asyncio.run(client.aclose())

    assert result[0].text == "før Maylen Sorkness Andersen etter"
    assert result[0].page_id is not None
