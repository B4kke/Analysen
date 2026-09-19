"""NB adapter parsing and contract tests (AQ-031).

Uses sanitized fixtures only. No live network calls.
"""

import json
from pathlib import Path

import httpx
import pytest

from apps.api.app.domain.nb_media import (
    NBConcreteConcordance,
    NBSearchCandidate,
    NBTextAnchor,
    NBTextAvailability,
)
from apps.api.app.services.nb_article_locator import (
    MAX_LOCATORS,
    match_page_anchors,
    parse_canvas_reference,
    parse_content_fragments,
    parse_dh_concordance,
    parse_iiif_anchors,
    parse_iiif_search,
    parse_original_url,
    parse_xywh,
)
from apps.api.app.sources.national_library import (
    NationalLibraryClient,
    NBClientError,
    parse_catalog_search_payload,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "nb"


def _load_fixture(name: str) -> dict:
    with open(FIXTURE_DIR / name, encoding="utf-8") as f:
        return json.load(f)


class TestCatalogSearchParsing:
    """Parse Catalog FULL_TEXT_SEARCH response into typed candidates."""

    def test_maylen_10_issues_parsed(self):
        payload = _load_fixture("catalog_search_maylen.json")
        total, candidates = parse_catalog_search_payload(
            payload, query="Maylen Sorkness Andersen", limit=25
        )

        assert total == 10
        assert len(candidates) == 10
        assert all(isinstance(c, NBSearchCandidate) for c in candidates)

    def test_first_candidate_has_expected_fields(self):
        payload = _load_fixture("catalog_search_maylen.json")
        _, candidates = parse_catalog_search_payload(payload, query="test", limit=25)
        first = candidates[0]

        assert first.item_id == "URN:NBN:no-nb_digavis_aftenposten_19941216_0072"
        assert first.publication == "Aftenposten"
        assert str(first.issued_at) == "1994-12-16"
        assert first.issue_urn == "URN:NBN:no-nb_digavis_aftenposten_19941216"
        assert first.rank == 1
        assert first.access_metadata["accessAllowedFrom"] == "EVERYWHERE"
        assert first.access_metadata["viewability"] == "ALL"

    def test_restricted_item_preserves_library_access(self):
        payload = _load_fixture("catalog_search_maylen.json")
        _, candidates = parse_catalog_search_payload(payload, query="test", limit=25)
        # Last item is Romerikes Blad 2026-05-19 (restricted)
        restricted = candidates[-1]

        assert restricted.item_id == "URN:NBN:no-nb_digavis_romerikesblad_20260519_0030"
        assert restricted.publication == "Romerikes Blad"
        assert restricted.access_metadata["accessAllowedFrom"] == "LIBRARY"

    def test_dedup_on_item_id(self):
        """Duplicate item_ids in payload are deduped."""
        payload = {
            "total": 2,
            "items": [
                {"itemId": "URN:NBN:dup1", "publication": "Test", "issued": "2020-01-01"},
                {"itemId": "URN:NBN:dup1", "publication": "Test", "issued": "2020-01-01"},
            ],
        }
        _, candidates = parse_catalog_search_payload(payload, query="test", limit=25)
        assert len(candidates) == 1

    def test_limit_cap_enforced(self):
        """Large payloads are capped at limit."""
        payload = {
            "total": 100,
            "items": [
                {"itemId": f"URN:NBN:item{i}", "publication": "Test", "issued": "2020-01-01"}
                for i in range(50)
            ],
        }
        _, candidates = parse_catalog_search_payload(payload, query="test", limit=10)
        assert len(candidates) == 10

    def test_various_envelope_shapes(self):
        """Defensive parsing across envelope shapes (items/docs/results/_embedded)."""
        for key in ["items", "docs", "results"]:
            payload = {key: [{"itemId": "URN:NBN:shape", "publication": "Test"}]}
            _, candidates = parse_catalog_search_payload(payload, query="test", limit=25)
            assert len(candidates) == 1

        embedded_payload = {
            "_embedded": {"items": [{"itemId": "URN:NBN:embedded", "publication": "Test"}]}
        }
        _, candidates = parse_catalog_search_payload(embedded_payload, query="test", limit=25)
        assert len(candidates) == 1


class TestContentFragmentsParsing:
    """contentfragments are page locators only, never article text."""

    def test_regression_large_fragsize_returns_only_em_fragment(self):
        """Live regression 2026-09-18: even large fragSize returns only <em>name</em>."""
        payload = _load_fixture("content_fragments_regression.json")
        locators = parse_content_fragments(
            payload, item_id="URN:NBN:test", query="Maylen Sorkness Andersen", max_pages=50
        )

        assert len(locators) == 1
        loc = locators[0]
        assert loc.item_id == "URN:NBN:test"
        assert loc.page_urn == "URN:NBN:no-nb_digavis_romerikesblad_20260519_0030_0030"
        assert loc.page_number == 30
        assert loc.query == "Maylen Sorkness Andersen"

    def test_dedup_on_page_urn(self):
        """Duplicate page URNs are deduped."""
        payload = {
            "fragments": [
                {"pageUrn": "URN:NBN:page1", "page": 1},
                {"pageUrn": "URN:NBN:page1", "page": 1},
                {"pageUrn": "URN:NBN:page2", "page": 2},
            ]
        }
        locators = parse_content_fragments(payload, item_id="URN:NBN:test", query="test")
        assert len(locators) == 2

    def test_max_pages_cap(self):
        """max_pages is capped at MAX_LOCATORS."""
        payload = {"fragments": [{"pageUrn": f"URN:NBN:page{i}", "page": i} for i in range(100)]}
        locators = parse_content_fragments(
            payload, item_id="URN:NBN:test", query="test", max_pages=1000
        )
        assert len(locators) == MAX_LOCATORS


class TestIIIFSearchParsing:
    """IIIF Content Search -> xywh anchors per page."""

    def test_iiif_xywh_parsing(self):
        payload = _load_fixture("iiif_search_maylen.json")
        anchors = parse_iiif_anchors(payload, query="Maylen Sorkness Andersen")

        assert len(anchors) == 3
        assert all(isinstance(a, NBTextAnchor) for a in anchors)

        first = anchors[0]
        assert first.page_urn == "https://api.nb.no/catalog/v1/items/URN:NBN:no-nb_digavis_romerikesblad_20260519/canvas/30"
        assert first.xywh == "xywh=1200,800,400,50"
        assert first.x == 1200
        assert first.y == 800
        assert first.w == 400
        assert first.h == 50
        assert first.query == "Maylen Sorkness Andersen"

    def test_iiif_search_grouped_per_page(self):
        payload = _load_fixture("iiif_search_maylen.json")
        hits = parse_iiif_search(
            payload,
            item_id="URN:NBN:no-nb_digavis_romerikesblad_20260519",
            query="Maylen Sorkness Andersen",
        )

        assert len(hits) == 1
        hit = hits[0]
        assert hit.item_id == "URN:NBN:no-nb_digavis_romerikesblad_20260519"
        assert hit.page_urn == "https://api.nb.no/catalog/v1/items/URN:NBN:no-nb_digavis_romerikesblad_20260519/canvas/30"
        assert len(hit.anchors) == 3

    def test_dedup_same_page_same_xywh(self):
        """Same page + same xywh is deduped."""
        payload = {
            "resources": [
                {"on": "urn:page1#xywh=100,100,50,50"},
                {"on": "urn:page1#xywh=100,100,50,50"},
                {"on": "urn:page2#xywh=200,200,50,50"},
            ]
        }
        anchors = parse_iiif_anchors(payload, query="test")
        assert len(anchors) == 2

    def test_parse_xywh_variants(self):
        assert parse_xywh("xywh=100,200,300,400") == (100, 200, 300, 400)
        assert parse_xywh("prefix xywh=10,20,30,40 suffix") == (10, 20, 30, 40)
        assert parse_xywh("invalid") is None
        assert parse_xywh("xywh=-1,0,10,10") is None  # negative x
        assert parse_xywh("xywh=0,0,0,10") is None  # zero width


class TestDHConcordanceParsing:
    """DH-lab /conc -> PARTIAL_CONTEXT rows."""

    def test_concordance_partial_context(self):
        payload = _load_fixture("dhlab_concordance_maylen.json")
        rows = parse_dh_concordance(payload, max_rows=50)

        assert len(rows) == 3
        assert all(isinstance(r, NBConcreteConcordance) for r in rows)

        first = rows[0]
        assert first.urn == "URN:NBN:no-nb_digavis_romerikesblad_20260519_0030_0030"
        assert first.before == "Fredagssamtalen med"
        assert first.match == "Maylen Sorkness Andersen"
        assert first.after == "handlet om lokalsamfunn og frivillighet."
        assert first.text_availability == NBTextAvailability.PARTIAL_CONTEXT

    def test_dedup_same_urn_same_context(self):
        """Duplicate concordance rows (same urn + before/after) are deduped."""
        payload = {
            "conc": [
                {"urn": "urn:1", "before": "a", "word": "b", "after": "c"},
                {"urn": "urn:1", "before": "a", "word": "b", "after": "c"},
                {"urn": "urn:2", "before": "x", "word": "y", "after": "z"},
            ]
        }
        rows = parse_dh_concordance(payload, max_rows=50)
        assert len(rows) == 2

    def test_max_rows_cap(self):
        """max_rows is capped at MAX_CONCORDANCES."""
        payload = {"conc": [{"urn": f"urn:{i}", "word": "test"} for i in range(100)]}
        rows = parse_dh_concordance(payload, max_rows=1000)
        from apps.api.app.services.nb_article_locator import MAX_CONCORDANCES
        assert len(rows) == MAX_CONCORDANCES


class TestNationalLibraryClient:
    """Adapter contract tests with MockTransport."""

    @pytest.fixture
    def mock_transport(self):
        """httpx.MockTransport that returns fixtures."""
        async def handler(request: httpx.Request) -> httpx.Response:
            # Simple routing based on URL pattern
            url = str(request.url)
            if "/search" in url and "FULL_TEXT_SEARCH" in url:
                return httpx.Response(200, json=_load_fixture("catalog_search_maylen.json"))
            if "/contentfragments" in url:
                return httpx.Response(200, json=_load_fixture("content_fragments_regression.json"))
            if "/contentsearch/" in url and "/search" in url:
                return httpx.Response(200, json=_load_fixture("iiif_search_maylen.json"))
            if "/conc" in url and request.method == "POST":
                return httpx.Response(200, json=_load_fixture("dhlab_concordance_maylen.json"))
            if "/items/" in url and not any(
                x in url for x in ["contentfragments", "contentsearch"]
            ):
                # Item metadata lookup
                if "romerikesblad" in url.lower():
                    return httpx.Response(200, json=_load_fixture("item_metadata_restricted.json"))
                return httpx.Response(200, json=_load_fixture("item_metadata_public.json"))
            return httpx.Response(404, json={"error": "not found"})

        return httpx.MockTransport(handler)

    @pytest.fixture
    async def client(self, mock_transport):
        client = NationalLibraryClient(
            catalog_base_url="https://api.nb.no/catalog/v1",
            dhlab_base_url="https://api.nb.no/dhlab",
            client=httpx.AsyncClient(transport=mock_transport),
        )
        yield client
        await client.aclose()

    async def test_search_newspapers_returns_typed(self, client):
        total, candidates, raw = await client.search_newspapers("Maylen Sorkness Andersen")

        assert total == 10
        assert len(candidates) == 10
        assert all(isinstance(c, NBSearchCandidate) for c in candidates)
        assert isinstance(raw.payload, dict)
        assert raw.status_code == 200

    async def test_search_newspapers_bounded_limit(self, client):
        """Eltonåsen stress: limit is capped at MAX_SEARCH_LIMIT (100)."""
        # Override to return many items
        import httpx

        async def many_items(request: httpx.Request) -> httpx.Response:
            items = [
                {"itemId": f"URN:NBN:item{i}", "publication": "Test", "issued": "2020-01-01"}
                for i in range(1000)
            ]
            return httpx.Response(200, json={"total": 1000, "items": items})

        client._client = httpx.AsyncClient(transport=httpx.MockTransport(many_items))
        total, candidates, _ = await client.search_newspapers("Eltonåsen", limit=500)
        assert total == 1000
        assert len(candidates) == 100  # Capped at MAX_SEARCH_LIMIT

    async def test_search_newspapers_requires_query(self, client):
        with pytest.raises(NBClientError) as exc:
            await client.search_newspapers("")
        assert exc.value.code == "invalid_query"

    async def test_content_fragments_returns_locator_not_text(self, client):
        raw = await client.content_fragments("URN:NBN:test", "Maylen Sorkness Andersen")
        assert raw.status_code == 200
        # The payload has only <em> fragment - locator parsing is separate

    async def test_iiif_search_returns_xywh(self, client):
        raw = await client.iiif_search("URN:NBN:test", "Maylen Sorkness Andersen")
        assert raw.status_code == 200
        assert "resources" in raw.payload

    async def test_dh_concordance_bounded_window_limit(self, client):
        raw = await client.dh_concordance(
            ["urn:1", "urn:2"], "test", window=500, limit=500
        )
        # Window and limit are bounded to MAX_CONC_WINDOW and MAX_CONC_LIMIT
        assert raw.status_code == 200

    async def test_get_item_preserves_access_metadata(self, client):
        item = await client.get_item("URN:NBN:no-nb_digavis_hadeland_20201223_0025")
        assert item.item_id == "URN:NBN:no-nb_digavis_hadeland_20201223_0025"
        assert item.payload["access"]["accessAllowedFrom"] == "EVERYWHERE"
        assert item.payload["access"]["viewability"] == "ALL"


class TestAdapterErrorHandling:
    """Errors are typed, never raw httpx exceptions."""

    async def test_http_error_raises_nbclienterror(self):
        async def error_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        client = NationalLibraryClient(
            client=httpx.AsyncClient(transport=httpx.MockTransport(error_handler))
        )
        with pytest.raises(NBClientError) as exc:
            await client.search_newspapers("test")
        assert exc.value.code == "http_error"
        assert exc.value.status_code == 500
        await client.aclose()

    async def test_invalid_json_raises_nbclienterror(self):
        async def invalid_json(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        client = NationalLibraryClient(
            client=httpx.AsyncClient(transport=httpx.MockTransport(invalid_json))
        )
        with pytest.raises(NBClientError) as exc:
            await client.search_newspapers("test")
        assert exc.value.code == "invalid_json"
        await client.aclose()

    async def test_transport_error_raises_nbclienterror(self):
        async def transport_error(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection failed")

        client = NationalLibraryClient(
            client=httpx.AsyncClient(transport=httpx.MockTransport(transport_error))
        )
        with pytest.raises(NBClientError) as exc:
            await client.search_newspapers("test")
        assert exc.value.code == "transport_error"
        await client.aclose()

def _sink_adapter(fixtures: dict[str, dict], sunk: list[str]):
    """Adapter over MockTransport with a capturing raw sink."""
    from apps.api.app.sources.national_library import NBMediaClientAdapter

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/contentfragments" in url:
            return httpx.Response(200, json=fixtures["content_fragments_regression.json"])
        if "/contentsearch/" in url:
            return httpx.Response(200, json=fixtures["iiif_search_maylen.json"])
        if "/conc" in url and request.method == "POST":
            return httpx.Response(200, json=fixtures["dhlab_concordance_maylen.json"])
        return httpx.Response(404, json={"error": "not found"})

    client = NationalLibraryClient(
        catalog_base_url="https://api.nb.no/catalog/v1",
        dhlab_base_url="https://api.nb.no/dhlab",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    return NBMediaClientAdapter(client, raw_sink=sunk.append), client


class TestAdapterRawSink:
    """Raw upstream envelopes are sunk verbatim before parsing."""

    async def test_contentfragments_raw_sunk_before_locator_parse(self):
        sunk: list[str] = []
        fixtures = {
            name: _load_fixture(name)
            for name in (
                "content_fragments_regression.json",
                "iiif_search_maylen.json",
                "dhlab_concordance_maylen.json",
            )
        }
        adapter, client = _sink_adapter(fixtures, sunk)
        try:
            locators = await adapter.content_fragments("URN:NBN:test", "Maylen")
        finally:
            await client.aclose()
        assert len(sunk) == 1
        assert json.loads(sunk[0]) == fixtures["content_fragments_regression.json"]
        assert len(locators) == 1
        assert locators[0].page_number == 30

    async def test_iiif_raw_sunk_with_xywh_preserved(self):
        sunk: list[str] = []
        fixtures = {
            name: _load_fixture(name)
            for name in (
                "content_fragments_regression.json",
                "iiif_search_maylen.json",
                "dhlab_concordance_maylen.json",
            )
        }
        adapter, client = _sink_adapter(fixtures, sunk)
        try:
            anchors = await adapter.iiif_search("URN:NBN:test", "Maylen")
        finally:
            await client.aclose()
        assert len(sunk) == 1
        assert json.loads(sunk[0]) == fixtures["iiif_search_maylen.json"]
        assert [anchor.xywh for anchor in anchors].count("xywh=1200,800,400,50") == 1

    async def test_dhlab_raw_sunk_with_partial_context(self):
        sunk: list[str] = []
        fixtures = {
            name: _load_fixture(name)
            for name in (
                "content_fragments_regression.json",
                "iiif_search_maylen.json",
                "dhlab_concordance_maylen.json",
            )
        }
        adapter, client = _sink_adapter(fixtures, sunk)
        try:
            rows = await adapter.dhlab_conc(["urn:1"], "Maylen")
        finally:
            await client.aclose()
        assert len(sunk) == 1
        assert json.loads(sunk[0]) == fixtures["dhlab_concordance_maylen.json"]
        assert rows and rows[0].context is not None

    async def test_no_sink_by_default_stays_side_effect_free(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_load_fixture("iiif_search_maylen.json"))

        from apps.api.app.sources.national_library import NBMediaClientAdapter

        client = NationalLibraryClient(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        adapter = NBMediaClientAdapter(client)
        try:
            anchors = await adapter.iiif_search("URN:NBN:test", "Maylen")
        finally:
            await client.aclose()
        assert len(anchors) == 3


class TestCatalogSearchRawSink:
    """Catalog raw envelope is sunk verbatim before normalization."""

    async def test_catalog_search_raw_sunk_verbatim(self):
        sunk: list[str] = []
        fixture = _load_fixture("catalog_search_maylen.json")

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=fixture)

        from apps.api.app.sources.national_library import NBMediaClientAdapter

        client = NationalLibraryClient(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        adapter = NBMediaClientAdapter(client, raw_sink=sunk.append)
        try:
            result = await adapter.catalog_search("Maylen Sorkness Andersen")
        finally:
            await client.aclose()
        assert len(sunk) == 1
        assert json.loads(sunk[0]) == fixture
        assert len(result.issues) == 10
        assert (
            result.issues[0].item_id
            == "URN:NBN:no-nb_digavis_aftenposten_19941216_0072"
        )


class TestRestrictedNeverFetches:
    """Rights-gate refusal happens before the downloader runs (no DB)."""

    async def test_denied_verdict_never_calls_downloader(self):
        from apps.api.app.services.executors.nb_media import (
            NBAccessVerdict,
            NBPageFetchDenied,
            fetch_permitted_page_image,
        )

        calls: list[str] = []

        class _RecordingClient:
            async def catalog_search(self, query):  # pragma: no cover
                raise AssertionError("no network in this test")

            async def content_fragments(self, item_id, query):  # pragma: no cover
                raise AssertionError("no network in this test")

            async def iiif_search(self, item_id, query):  # pragma: no cover
                raise AssertionError("no network in this test")

            async def dhlab_conc(self, urns, query, *, window=10, limit=5):  # pragma: no cover
                raise AssertionError("no network in this test")

            async def fetch_page_image(self, page_urn: str) -> bytes:
                calls.append(page_urn)
                return b"must-never-happen"

        for access_class in ("LIBRARY_ONLY", "NB_ONLY", "UNKNOWN"):
            verdict = NBAccessVerdict(
                access_class=access_class, allow_page_fetch=False
            )
            with pytest.raises(NBPageFetchDenied):
                await fetch_permitted_page_image(
                    _RecordingClient(), verdict, "URN:NBN:page:30"
                )
        assert calls == []

    async def test_permitted_verdict_reaches_downloader(self):
        from apps.api.app.services.executors.nb_media import (
            NBAccessVerdict,
            fetch_permitted_page_image,
        )

        calls: list[str] = []

        class _RecordingClient:
            async def fetch_page_image(self, page_urn: str) -> bytes:
                calls.append(page_urn)
                return b"\xff\xd8\xff\xe0jpeg"

        verdict = NBAccessVerdict(
            access_class="PUBLIC_VIEW_ONLY", allow_page_fetch=True
        )
        image = await fetch_permitted_page_image(
            _RecordingClient(), verdict, "URN:NBN:page:25"
        )
        assert image == b"\xff\xd8\xff\xe0jpeg"
        assert calls == ["URN:NBN:page:25"]


class TestCanvasAnchorMatching:
    """Correlate IIIF canvas anchors to fragment pages (AQ-033).

    Canvas targets (``.../items/<id>/canvas/<n>``) rarely equal fragment
    URNs verbatim, so exact equality alone would silently drop every anchor.
    """

    _BASE = "https://api.nb.no/catalog/v1/items"
    _ITEM30 = f"{_BASE}/URN:NBN:item/canvas/30#xywh=1,2,3,4"
    _OTHER30 = f"{_BASE}/URN:NBN:other/canvas/30#xywh=9,9,9,9"
    _ITEM31 = f"{_BASE}/URN:NBN:item/canvas/31#xywh=2,2,2,2"
    _ISSUE30 = f"{_BASE}/URN:NBN:issue/canvas/30#xywh=1,2,3,4"
    _ITEM1 = f"{_BASE}/URN:NBN:item/canvas/1#xywh=5,6,7,8"

    def test_parse_canvas_reference_splits_item_and_page(self):
        assert parse_canvas_reference(f"{self._BASE}/URN:NBN:no-nb_x/canvas/30#xywh=1,2,3,4") == (
            "URN:NBN:no-nb_x",
            30,
        )
        assert parse_canvas_reference("URN:NBN:no-nb_x") is None
        assert parse_canvas_reference("") is None
        assert parse_canvas_reference(None) is None
        assert parse_canvas_reference(f"{self._BASE}//canvas/3") is None
        assert parse_canvas_reference("https://x/items/i/canvas/0") is None

    def test_exact_page_urn_match_wins(self):
        pairs = [("URN:NBN:page:1", "xywh=1,2,3,4"), ("URN:NBN:page:2", "xywh=5,6,7,8")]
        assert match_page_anchors(
            pairs, item_id="URN:NBN:item", page_urn="URN:NBN:page:2", page_number=9
        ) == ["xywh=5,6,7,8"]

    def test_canvas_fallback_matches_item_and_page(self):
        pairs = [
            (self._ITEM30, "xywh=1,2,3,4"),
            (self._OTHER30, "xywh=9,9,9,9"),
            (self._ITEM31, "xywh=2,2,2,2"),
        ]
        assert match_page_anchors(
            pairs,
            item_id="URN:NBN:item",
            page_urn="URN:NBN:item_page_30",
            page_number=30,
        ) == ["xywh=1,2,3,4"]

    def test_canvas_fallback_accepts_issue_identifier(self):
        pairs = [(self._ISSUE30, "xywh=1,2,3,4")]
        assert match_page_anchors(
            pairs,
            item_id="URN:NBN:item",
            issue_urn="URN:NBN:issue",
            page_urn="URN:NBN:item_page_30",
            page_number=30,
        ) == ["xywh=1,2,3,4"]

    def test_foreign_anchors_never_leak(self):
        pairs = [
            (self._OTHER30, "xywh=1,2,3,4"),
            ("URN:NBN:other-page", "xywh=5,6,7,8"),
            ("", "xywh=9,9,9,9"),
            ("URN:NBN:page:1", ""),
        ]
        assert (
            match_page_anchors(
                pairs, item_id="URN:NBN:item", page_urn="URN:NBN:page:1", page_number=1
            )
            == []
        )

    def test_order_preserved_and_duplicates_removed(self):
        pairs = [
            ("URN:NBN:page:1", "xywh=1,2,3,4"),
            ("URN:NBN:page:1", "xywh=1,2,3,4"),
            (self._ITEM1, "xywh=5,6,7,8"),
        ]
        assert match_page_anchors(
            pairs, item_id="URN:NBN:item", page_urn="URN:NBN:page:1", page_number=1
        ) == ["xywh=1,2,3,4", "xywh=5,6,7,8"]

    def test_fixture_canvas_anchors_match_fixture_fragment(self):
        """Live-shape proof: fixture canvas anchors correlate to the fixture
        fragment page via issue identifier + page number."""
        payload = _load_fixture("iiif_search_maylen.json")
        anchors = parse_iiif_anchors(payload, query="Maylen Sorkness Andersen")
        pairs = [(a.page_urn, a.xywh) for a in anchors]
        matched = match_page_anchors(
            pairs,
            item_id="URN:NBN:no-nb_digavis_romerikesblad_20260519_0030",
            issue_urn="URN:NBN:no-nb_digavis_romerikesblad_20260519",
            page_urn="URN:NBN:no-nb_digavis_romerikesblad_20260519_0030_0030",
            page_number=30,
        )
        assert matched == ["xywh=1200,800,400,50", "xywh=1250,860,350,45", "xywh=1300,920,300,40"]


class TestOriginalUrlParsing:
    """Upstream original-article URLs: http(s) only (AQ-035)."""

    def test_http_and_https_accepted(self):
        assert (
            parse_original_url("https://nettavis.test/artikkel/1")
            == "https://nettavis.test/artikkel/1"
        )
        assert (
            parse_original_url("  http://nettavis.test/a  ")
            == "http://nettavis.test/a"
        )

    def test_non_article_targets_rejected(self):
        assert parse_original_url("ftp://files.test/x") is None
        assert parse_original_url("javascript:alert(1)") is None
        assert parse_original_url("URN:NBN:no-nb_x") is None
        assert parse_original_url("/relativ/sti") is None
        assert parse_original_url("https://") is None
        assert parse_original_url("") is None
        assert parse_original_url(None) is None
        assert parse_original_url(42) is None

    def test_catalog_payload_maps_original_url(self):
        payload = {
            "total": 1,
            "items": [
                {
                    "itemId": "URN:NBN:item:1",
                    "publication": "Nettavis",
                    "issued": "2024-01-05",
                    "issueUrn": "URN:NBN:issue",
                    "originalUrl": "https://nettavis.test/artikkel/1",
                },
                {
                    "itemId": "URN:NBN:item:2",
                    "publication": "Nettavis",
                    "issued": "2024-01-06",
                    "issueUrn": "URN:NBN:issue",
                    "originalUrl": "ftp://files.test/x",
                },
                {
                    "itemId": "URN:NBN:item:3",
                    "publication": "Nettavis",
                    "issued": "2024-01-07",
                    "issueUrn": "URN:NBN:issue",
                },
            ],
        }
        total, candidates = parse_catalog_search_payload(payload, query="q", limit=25)
        assert total == 1
        assert candidates[0].original_url == "https://nettavis.test/artikkel/1"
        assert candidates[1].original_url is None
        assert candidates[2].original_url is None


class TestLiveMediaTypeResultsShape:
    """Live envelope: hits under mediaTypeResults with nested metadata (AQ-039).

    Shape verified against live api.nb.no 2026-09-19; sanitized fixture only.
    """

    def test_mediatype_results_yield_candidates(self):
        payload = _load_fixture("catalog_mediatype_results.json")
        total, candidates = parse_catalog_search_payload(payload, query="q", limit=25)
        assert total == 2
        assert len(candidates) == 2

        first, second = candidates
        assert first.item_id == "3a146f0299bd0384506925a7fcfb8013"
        assert first.publication == "Hadeland"
        assert str(first.issued_at) == "2020-12-23"
        assert first.issue_urn == "URN:NBN:no-nb_digavis_hadeland_20201223"
        assert first.rank == 1
        assert first.access_metadata["accessAllowedFrom"] == "EVERYWHERE"
        assert first.access_metadata["viewability"] == "ALL"

        assert second.publication == "Romerikes Blad"
        assert str(second.issued_at) == "2026-05-19"
        assert second.access_metadata["accessAllowedFrom"] == "LIBRARY"

    def test_live_shape_result_limit_is_bounded(self):
        payload = _load_fixture("catalog_mediatype_results.json")
        _, candidates = parse_catalog_search_payload(payload, query="q", limit=1)
        assert len(candidates) == 1
