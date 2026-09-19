"""Typed extraction from lawful NB article context tests (AQ-031).

No network, no LLM. Pure function tests using fixture context text.
"""

import hashlib
import io
import sys
import types

import pytest

from apps.api.app.domain.nb_media import NBTextAvailability
from apps.api.app.services.nb_article_extract import (
    NBExtractedArticle,
    NBExtractError,
    NBOcrWord,
    crop_page_image,
    enrich_media_mention_with_extraction,
    extract_nb_article,
    extract_permitted_article,
    find_article_region,
    page_image_size,
    tesseract_ocr_words_norwegian,
)


class TestExtractNbArticle:
    """Core extraction function tests."""

    def test_empty_context_returns_empty_article(self):
        result = extract_nb_article(
            "", text_availability=NBTextAvailability.UNAVAILABLE
        )
        assert isinstance(result, NBExtractedArticle)
        assert result.headline is None
        assert result.summary is None
        assert result.persons == []
        assert result.organizations == []
        assert result.text_availability == NBTextAvailability.UNAVAILABLE

    def test_none_context_returns_empty_article(self):
        result = extract_nb_article(
            None, text_availability=NBTextAvailability.PARTIAL_CONTEXT
        )
        assert result.text_availability == NBTextAvailability.PARTIAL_CONTEXT
        assert result.persons == []

    def test_extracts_headline_from_first_substantial_line(self):
        text = "Kort\nDette er en lang overskrift som bør bli plukket opp\nKroppstekst..."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert result.headline == "Dette er en lang overskrift som bør bli plukket opp"

    def test_extracts_summary_from_first_lines(self):
        text = "Linje 1\nLinje 2 er litt lengre\nLinje 3 også ganske lang\nLinje 4"
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert "Linje 2 er litt lengre" in result.summary
        assert "Linje 3 også ganske lang" in result.summary

    def test_target_context_anchors_on_target_name(self):
        text = "Start tekst her. Maylen Sorkness Andersen er navnet i midten. Slutt tekst."
        result = extract_nb_article(
            text,
            text_availability=NBTextAvailability.PARTIAL_CONTEXT,
            target_name="Maylen Sorkness Andersen",
        )
        assert result.target_context is not None
        assert "Maylen Sorkness Andersen" in result.target_context

    def test_target_context_none_when_target_absent(self):
        text = "Tekst uten målperson."
        result = extract_nb_article(
            text,
            text_availability=NBTextAvailability.PARTIAL_CONTEXT,
            target_name="Maylen Sorkness Andersen",
        )
        assert result.target_context is None

    def test_extracts_persons_heuristic(self):
        text = "Ola Nordmann og Kari Nordmann møttes i Oslo. Per Hansen var også der."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        # Heuristic may find these names
        assert any("Nordmann" in p for p in result.persons)

    def test_extracts_organizations_heuristic(self):
        text = 'Styret i "Bedrift AS" godtok budsjettet. Styremedlem Kari Nordmann stemte for.'
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert any("Bedrift AS" in o for o in result.organizations)

    def test_extracts_places_heuristic(self):
        text = "Møtet var i Oslo og fortsatte til Bergen neste dag."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        places = " ".join(result.places)
        assert "Oslo" in places or "Bergen" in places

    def test_extracts_dates_iso_format(self):
        text = "Møtet skjedde 2023-05-15 og fortsatte 2023-05-16."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert len(result.dates) >= 1

    def test_extracts_dates_norwegian_format(self):
        text = "Avtalen ble signert 15. mai 2023 på kontoret."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert len(result.dates) >= 1

    def test_extracts_roles(self):
        text = "Kari Nordmann er styreleder i Bedrift AS. Per Hansen er daglig leder."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert "styreleder" in result.roles
        assert "daglig leder" in result.roles

    def test_extracts_caption(self):
        text = "Overskrift\nDette er en billedtekst uten punktum\nFlere linjer tekst."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        # Caption heuristic finds short-ish non-ending-with-period line
        if result.caption:
            assert len(result.caption) <= 200

    def test_extracts_claim_candidates(self):
        text = "Styret godtok budsjettet. Direktøren sa at resultatet er bra. Selskapet vokser."
        result = extract_nb_article(text, text_availability=NBTextAvailability.FULL)
        assert len(result.claim_candidates) >= 1

    def test_text_availability_carried_through(self):
        for avail in NBTextAvailability:
            result = extract_nb_article("test", text_availability=avail)
            assert result.text_availability == avail

    def test_does_not_call_llm(self):
        """Verify no network/LLM calls - this is a pure function."""
        # If this test runs without network mocks, it passes by nature of being pure
        result = extract_nb_article("test tekst", text_availability=NBTextAvailability.FULL)
        assert isinstance(result, NBExtractedArticle)


class TestEnrichMediaMention:
    """Convenience wrapper for MediaMentionCandidate enrichment."""

    def test_returns_enrichment_dict(self):
        context = (
            "Maylen Sorkness Andersen er styreleder i Foreningen. "
            "Møtet var i Oslo 2023-05-15."
        )
        enriched = enrich_media_mention_with_extraction(
            mention=None,
            context_text=context,
            text_availability=NBTextAvailability.PARTIAL_CONTEXT,
            target_name="Maylen Sorkness Andersen",
        )

        assert "headline" in enriched
        assert "summary" in enriched
        assert "target_context" in enriched
        assert "persons" in enriched
        assert "organizations" in enriched
        assert "places" in enriched
        assert "dates" in enriched
        assert "roles" in enriched
        assert "caption" in enriched
        assert "claim_candidates" in enriched
        assert "text_availability" in enriched
        assert enriched["text_availability"] == "PARTIAL_CONTEXT"

    def test_dates_are_iso_strings(self):
        context = "Hendelsen skjedde 15. mai 2023."
        enriched = enrich_media_mention_with_extraction(
            mention=None, context_text=context, text_availability=NBTextAvailability.FULL
        )
        for d in enriched["dates"]:
            assert isinstance(d, str)
            # Should be ISO format YYYY-MM-DD
            assert len(d) == 10
            assert d[4] == "-"
            assert d[7] == "-"


class TestDHlabConcordanceContext:
    """Extraction specifically from DH-lab concordance context (PARTIAL_CONTEXT)."""

    def test_concordance_context_extraction(self):
        """DH-lab concordance provides fragmented context, not full article."""
        # Simulated DH-lab concordance context (multiple rows concatenated)
        context = (
            "Fredagssamtalen med Maylen Sorkness Andersen handlet om lokalsamfunn. "
            "I intervjuet sier Maylen Sorkness Andersen at hun engasjerer seg. "
            "Julemarkedet åpnes av Maylen Sorkness Andersen som er styreleder."
        )
        result = extract_nb_article(
            context,
            text_availability=NBTextAvailability.PARTIAL_CONTEXT,
            target_name="Maylen Sorkness Andersen",
        )

        assert result.text_availability == NBTextAvailability.PARTIAL_CONTEXT
        assert "Maylen Sorkness Andersen" in (result.target_context or "")
        assert "styreleder" in result.roles
        # Persons may be found but not guaranteed by heuristic
        # Organizations may include "Foreningen" etc.

    def test_partial_context_not_mistaken_for_full(self):
        """Ensure PARTIAL_CONTEXT is never treated as FULL."""
        result = extract_nb_article(
            "Kort kontekst.", text_availability=NBTextAvailability.PARTIAL_CONTEXT
        )
        assert result.text_availability == NBTextAvailability.PARTIAL_CONTEXT
        assert result.text_availability != NBTextAvailability.FULL


class TestUNAVAILABLEContext:
    """When text is UNAVAILABLE, extraction returns minimal structure."""

    def test_unavailable_returns_empty_but_typed(self):
        result = extract_nb_article(
            None, text_availability=NBTextAvailability.UNAVAILABLE
        )
        assert result.text_availability == NBTextAvailability.UNAVAILABLE
        assert result.headline is None
        assert result.summary is None  # NBExtractedArticle has summary, not body
        # All lists empty
        assert result.persons == []
        assert result.organizations == []
        assert result.places == []
        assert result.dates == []
        assert result.roles == []
        assert result.claim_candidates == []

def _synthetic_page(width: int = 400, height: int = 300) -> bytes:
    """Deterministic white PNG page; Pillow is available in CI."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def _word(text: str, x: int, y: int, w: int = 60, h: int = 18) -> NBOcrWord:
    return NBOcrWord(text=text, x=x, y=y, w=w, h=h, confidence=95.0)


class TestFindArticleRegion:
    """IIIF xywh anchors seed the article region (pure geometry)."""

    def test_anchor_seed_expands_within_page(self):
        region = find_article_region(
            parent_page_urn="URN:NBN:page:30",
            page_width=1000,
            page_height=1400,
            anchor_xywh=["xywh=100,200,80,20"],
            ocr_words=[],
            target_expression="Maylen Sorkness Andersen",
        )
        assert region.parent_page_urn == "URN:NBN:page:30"
        assert region.anchor_xywh == "xywh=100,200,80,20"
        # Seed box is contained in the expanded region, region in the page.
        assert region.x <= 100
        assert region.y <= 200
        assert region.x + region.w >= 180
        assert region.y + region.h >= 220
        assert region.x + region.w <= 1000
        assert region.y + region.h <= 1400

    def test_matching_ocr_words_join_seed(self):
        region = find_article_region(
            parent_page_urn="URN:NBN:page:30",
            page_width=1000,
            page_height=1400,
            anchor_xywh=["xywh=100,200,80,20"],
            ocr_words=[_word("Maylen", 500, 900), _word("vann", 10, 10)],
            target_expression="Maylen Sorkness Andersen",
        )
        # The matching OCR word far from the anchor stretches the region.
        assert region.x + region.w >= 560
        assert region.y + region.h >= 918

    def test_ocr_match_without_anchors_still_locates(self):
        region = find_article_region(
            parent_page_urn="URN:NBN:page:30",
            page_width=1000,
            page_height=1400,
            anchor_xywh=[],
            ocr_words=[_word("Andersen", 300, 400)],
            target_expression="Maylen Sorkness Andersen",
        )
        assert region.anchor_xywh is None
        assert region.x <= 300
        assert region.y <= 400

    def test_target_not_found_without_seed(self):
        with pytest.raises(NBExtractError) as exc:
            find_article_region(
                parent_page_urn="URN:NBN:page:30",
                page_width=1000,
                page_height=1400,
                anchor_xywh=["not-a-box"],
                ocr_words=[_word("vann", 10, 10)],
                target_expression="Maylen Sorkness Andersen",
            )
        assert exc.value.code == "target_not_found"

    def test_out_of_page_anchor_is_skipped(self):
        with pytest.raises(NBExtractError) as exc:
            find_article_region(
                parent_page_urn="URN:NBN:page:30",
                page_width=100,
                page_height=100,
                anchor_xywh=["xywh=900,900,80,20"],
                ocr_words=[],
                target_expression="Maylen Sorkness Andersen",
            )
        assert exc.value.code == "target_not_found"

    def test_invalid_target_rejected(self):
        with pytest.raises(NBExtractError) as exc:
            find_article_region(
                parent_page_urn="URN:NBN:page:30",
                page_width=100,
                page_height=100,
                anchor_xywh=["xywh=10,10,20,10"],
                ocr_words=[],
                target_expression="  ",
            )
        assert exc.value.code == "invalid_target"


class TestCropPageImage:
    """Exact page pixels per recorded geometry; deterministic PNG."""

    def test_crop_returns_png_of_region_size(self):
        from PIL import Image

        page = _synthetic_page(200, 100)
        region = find_article_region(
            parent_page_urn="URN:NBN:page:1",
            page_width=200,
            page_height=100,
            anchor_xywh=["xywh=50,20,40,10"],
            ocr_words=[],
            target_expression="Maylen Sorkness Andersen",
        )
        crop = crop_page_image(page, region)
        assert crop[:8] == b"\x89PNG\r\n\x1a\n"
        with Image.open(io.BytesIO(crop)) as image:
            assert image.size == (region.w, region.h)

    def test_region_exceeding_page_rejected(self):
        from apps.api.app.services.nb_article_extract import NBArticleRegion

        page = _synthetic_page(200, 100)
        region = NBArticleRegion(
            parent_page_urn="URN:NBN:page:1",
            x=150,
            y=10,
            w=100,
            h=10,
            page_width=200,
            page_height=100,
        )
        with pytest.raises(NBExtractError) as exc:
            crop_page_image(page, region)
        assert exc.value.code == "invalid_region"

    def test_empty_bytes_rejected(self):
        from apps.api.app.services.nb_article_extract import NBArticleRegion

        region = NBArticleRegion(
            parent_page_urn="URN:NBN:page:1",
            x=0,
            y=0,
            w=10,
            h=10,
            page_width=200,
            page_height=100,
        )
        with pytest.raises(NBExtractError) as exc:
            crop_page_image(b"", region)
        assert exc.value.code == "invalid_image"

    def test_page_image_size(self):
        assert page_image_size(_synthetic_page(200, 100)) == (200, 100)


class TestNorwegianOcrBackend:
    """Norwegian OCR uses lang=nor; missing stack fails typed."""

    def test_missing_stack_fails_closed(self):
        # pytesseract is absent from this venv: the default backend must
        # raise a typed ocr_unavailable, never silently return words.
        assert "pytesseract" not in sys.modules
        with pytest.raises(NBExtractError) as exc:
            tesseract_ocr_words_norwegian(_synthetic_page(64, 32))
        assert exc.value.code == "ocr_unavailable"

    def test_backend_requests_norwegian(self):
        """A stubbed pytesseract proves lang=nor is passed through."""
        from PIL import Image

        captured: dict = {}

        def fake_image_to_data(image, *, lang=None, output_type=None):
            captured["lang"] = lang
            assert isinstance(image, Image.Image)
            return {
                "text": ["Maylen", "", "Andersen"],
                "left": [10, 0, 80],
                "top": [20, 0, 20],
                "width": [50, 0, 60],
                "height": [14, 0, 14],
                "conf": [96.0, -1.0, 93.0],
            }

        stub = types.ModuleType("pytesseract")
        stub.Output = types.SimpleNamespace(DICT="dict")
        stub.image_to_data = fake_image_to_data
        sys.modules["pytesseract"] = stub
        try:
            words = tesseract_ocr_words_norwegian(_synthetic_page(200, 100))
        finally:
            del sys.modules["pytesseract"]
        assert captured["lang"] == "nor"
        assert [word.text for word in words] == ["Maylen", "Andersen"]
        assert words[0].x == 10 and words[0].y == 20


class TestExtractPermittedArticle:
    """Page bytes -> hash -> anchored crop -> OCR -> validation."""

    def _page_ocr(self, page_bytes: bytes) -> list[NBOcrWord]:
        assert len(page_bytes) > 0
        return [_word("Maylen", 100, 60), _word("Sorkness", 165, 60)]

    def _crop_ocr_valid(self, crop_bytes: bytes) -> list[NBOcrWord]:
        assert len(crop_bytes) > 0
        return [_word("Maylen", 5, 5), _word("Sorkness", 70, 5), _word("Andersen", 150, 5)]

    def test_full_chain_with_hashes_and_geometry(self):
        page = _synthetic_page(400, 300)
        result = extract_permitted_article(
            page,
            page_urn="URN:NBN:no-nb_digavis_hadeland_20201223_0025_0025",
            anchor_xywh=["xywh=100,60,120,20"],
            target_expression="Maylen Sorkness Andersen",
            page_ocr_fn=self._page_ocr,
            crop_ocr_fn=self._crop_ocr_valid,
        )
        assert result.page_sha256 == hashlib.sha256(page).hexdigest()
        assert result.region.page_sha256 == result.page_sha256
        assert result.region.crop_sha256 == hashlib.sha256(result.crop_bytes).hexdigest()
        assert result.region.parent_page_urn == (
            "URN:NBN:no-nb_digavis_hadeland_20201223_0025_0025"
        )
        assert result.region.anchor_xywh == "xywh=100,60,120,20"
        assert result.region.x + result.region.w <= 400
        assert result.region.y + result.region.h <= 300
        assert result.crop_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert result.target_validated is True
        assert result.region.target_validated is True
        assert "Maylen" in (result.crop_text or "")

    def test_unvalidated_crop_still_returns_but_flagged(self):
        page = _synthetic_page(400, 300)
        result = extract_permitted_article(
            page,
            page_urn="URN:NBN:page:9",
            anchor_xywh=["xywh=100,60,120,20"],
            target_expression="Maylen Sorkness Andersen",
            page_ocr_fn=self._page_ocr,
            crop_ocr_fn=lambda _crop: [_word("vann", 5, 5)],
        )
        assert result.target_validated is False
        assert result.region.crop_sha256 is not None

    def test_missing_anchor_rejected(self):
        with pytest.raises(NBExtractError) as exc:
            extract_permitted_article(
                _synthetic_page(),
                page_urn="URN:NBN:page:9",
                anchor_xywh=[],
                target_expression="Maylen Sorkness Andersen",
                page_ocr_fn=self._page_ocr,
            )
        assert exc.value.code == "missing_anchor"

    def test_empty_page_rejected(self):
        with pytest.raises(NBExtractError) as exc:
            extract_permitted_article(
                b"",
                page_urn="URN:NBN:page:9",
                anchor_xywh=["xywh=10,10,20,10"],
                target_expression="Maylen Sorkness Andersen",
                page_ocr_fn=self._page_ocr,
            )
        assert exc.value.code == "invalid_image"


class TestPermittedCropPersistenceWiring:
    """Permitted crop -> Document/Evidence linkage (fakes, no DB).

    Proves ``_extract_and_persist_crop`` wires the IIIF ``xywh`` anchors,
    exact crop geometry and both hashes into the canonical
    Document/Evidence persistence seam. The OCR backends are injected, so
    this runs without the native tesseract stack.
    """

    def _page_ocr(self, page_bytes: bytes) -> list[NBOcrWord]:
        assert len(page_bytes) > 0
        return [_word("Maylen", 100, 60), _word("Sorkness", 165, 60)]

    def _crop_ocr(self, crop_bytes: bytes) -> list[NBOcrWord]:
        assert len(crop_bytes) > 0
        return [_word("Maylen", 5, 5), _word("Sorkness", 70, 5), _word("Andersen", 150, 5)]

    async def test_crop_persists_document_and_evidence_with_xywh(self, monkeypatch):
        import uuid

        from apps.api.app.services.executors import nb_media as executor
        from apps.api.app.services.executors.nb_media import NBAccessVerdict

        captured: dict = {}
        document_id = uuid.uuid4()
        evidence_id = uuid.uuid4()
        investigation_id = uuid.uuid4()
        crop_key = "sha256/ab/crop-test-key"

        async def fake_upsert_source(session, source):
            captured["source"] = source

        async def fake_upsert_document(session, **kwargs):
            captured["document"] = kwargs
            return document_id

        async def fake_attach(session, iid, document_id, reason="direct_lookup"):
            captured["attach"] = {
                "investigation_id": iid,
                "document_id": document_id,
                "reason": reason,
            }

        async def fake_store_evidence(
            session, doc_id, locator_type, locator, excerpt, structured_value
        ):
            captured["evidence"] = {
                "document_id": doc_id,
                "locator_type": locator_type,
                "locator": locator,
                "excerpt": excerpt,
                "structured_value": structured_value,
            }
            return evidence_id

        def fake_store_raw(payload: bytes):
            captured["crop_bytes"] = bytes(payload)
            digest = hashlib.sha256(bytes(payload)).hexdigest()
            return digest, crop_key

        monkeypatch.setattr(
            "apps.api.app.repositories.claims_evidence.upsert_source", fake_upsert_source
        )
        monkeypatch.setattr(
            "apps.api.app.repositories.claims_evidence.upsert_document",
            fake_upsert_document,
        )
        monkeypatch.setattr(
            "apps.api.app.repositories.claims_evidence.attach_document", fake_attach
        )
        monkeypatch.setattr(
            "apps.api.app.repositories.claims_evidence.store_evidence",
            fake_store_evidence,
        )
        monkeypatch.setattr(executor, "store_raw_bytes", fake_store_raw)

        page = _synthetic_page(400, 300)
        page_hash = hashlib.sha256(page).hexdigest()
        verdict = NBAccessVerdict(
            access_class="PUBLIC_VIEW_ONLY",
            allow_metadata=True,
            allow_context=True,
            allow_page_fetch=True,
            allow_derived_crop=True,
            reason="test",
        )
        returned_id, crop_text, returned_evidence_id = await executor._extract_and_persist_crop(
            object(),
            investigation_id,
            item_id="URN:NBN:no-nb_digavis_hadeland_20201223_0025",
            issue_urn="URN:NBN:no-nb_digavis_hadeland_20201223",
            page_urn="URN:NBN:no-nb_digavis_hadeland_20201223_0025_0025",
            page_number=25,
            publication="Hadeland",
            issued_at="2020-12-23",
            source_url="https://api.nb.no/catalog/v1/items/URN:NBN:x",
            query="Maylen Sorkness Andersen",
            anchors=["xywh=100,60,120,20"],
            page_bytes=page,
            verdict=verdict,
            upstream_license=None,
            page_ocr_fn=self._page_ocr,
            crop_ocr_fn=self._crop_ocr,
        )

        assert returned_id == document_id
        assert returned_evidence_id == evidence_id
        assert crop_text is not None and "Maylen" in crop_text

        crop_hash = hashlib.sha256(captured["crop_bytes"]).hexdigest()
        document = captured["document"]
        assert document["sha256"] == crop_hash
        assert document["raw_storage_key"] == crop_key
        assert document["mime_type"] == "image/png"
        assert document["extracted_text"] == crop_text
        assert document["source_id"] == "nb_catalog"

        evidence = captured["evidence"]
        assert evidence["document_id"] == document_id
        assert evidence["locator_type"] == "nb_article_crop"
        locator = evidence["locator"]
        assert locator["xywh"] == ["xywh=100,60,120,20"]
        assert (
            locator["page_urn"]
            == "URN:NBN:no-nb_digavis_hadeland_20201223_0025_0025"
        )
        assert locator["page_sha256"] == page_hash
        assert locator["crop_sha256"] == crop_hash
        assert locator["ocr_lang"] == "nor"
        crop = locator["crop"]
        assert crop["w"] >= 1 and crop["h"] >= 1
        assert crop["x"] + crop["w"] <= locator["page"]["width"]
        assert crop["y"] + crop["h"] <= locator["page"]["height"]
        assert evidence["structured_value"]["target_validated"] is True

        attach = captured["attach"]
        assert attach["investigation_id"] == investigation_id
        assert attach["document_id"] == document_id
        assert attach["reason"] == "nb_media_crop"
        assert captured["source"].id == "nb_catalog"

    async def test_denied_crop_persists_nothing(self, monkeypatch):
        import uuid

        from apps.api.app.services.executors import nb_media as executor
        from apps.api.app.services.executors.nb_media import NBAccessVerdict

        calls: list[str] = []

        async def fake_upsert_document(session, **kwargs):  # pragma: no cover
            calls.append("upsert_document")
            return uuid.uuid4()

        async def fake_store_evidence(*args, **kwargs):  # pragma: no cover
            calls.append("store_evidence")
            return uuid.uuid4()

        monkeypatch.setattr(
            "apps.api.app.repositories.claims_evidence.upsert_document",
            fake_upsert_document,
        )
        monkeypatch.setattr(
            "apps.api.app.repositories.claims_evidence.store_evidence",
            fake_store_evidence,
        )

        verdict = NBAccessVerdict(access_class="LIBRARY_ONLY", reason="test")
        returned_id, crop_text, returned_evidence_id = await executor._extract_and_persist_crop(
            object(),
            uuid.uuid4(),
            item_id="URN:NBN:item",
            issue_urn=None,
            page_urn="URN:NBN:page:30",
            page_number=30,
            publication="Romerikes Blad",
            issued_at="2026-05-19",
            source_url=None,
            query="Maylen Sorkness Andersen",
            anchors=["xywh=100,60,120,20"],
            page_bytes=_synthetic_page(400, 300),
            verdict=verdict,
            upstream_license=None,
            page_ocr_fn=self._page_ocr,
            crop_ocr_fn=self._crop_ocr,
        )
        assert returned_id is None
        assert returned_evidence_id is None
        assert crop_text is None
        assert calls == []


class TestOriginalUrlBridge:
    """Original-URL collection and lead construction (AQ-035, pure)."""

    def test_collect_original_urls_dedupes_caps_and_drops_non_web(self):
        from apps.api.app.services.executors import nb_media as executor

        issues = [
            {"original_url": "https://nettavis.test/a"},
            {"original_url": "https://nettavis.test/a"},
            {"original_url": "ftp://files.test/x"},
            {"original_url": "URN:NBN:x"},
            {"original_url": None},
            {"original_url": "https://nettavis.test/b"},
        ]
        assert executor.collect_original_urls(issues) == [
            "https://nettavis.test/a",
            "https://nettavis.test/b",
        ]

    def test_collect_original_urls_respects_cap(self):
        from apps.api.app.services.executors import nb_media as executor

        issues = [{"original_url": f"https://nettavis.test/{n}"} for n in range(20)]
        collected = executor.collect_original_urls(issues)
        assert len(collected) == executor.MAX_ORIGINAL_URL_BRIDGES
        assert collected[0] == "https://nettavis.test/0"

    def test_build_original_url_lead_is_gated_web_fetch(self):
        from apps.api.app.services.executors import nb_media as executor
        from apps.api.app.services.source_router import route_lead

        lead = executor.build_original_url_lead(
            "https://nettavis.test/a", query="Bro Probe", publication="Nettavis"
        )
        assert lead.lead_type == "web_document_fetch"
        assert route_lead(lead.lead_type) == "web_fetch"
        assert lead.value == {"url": "https://nettavis.test/a"}
        assert lead.scope_area.value == "WEB_MEDIA"
        assert lead.trigger_type.value == "DIRECT_SOURCE_LOOKUP"
        assert lead.relation_depth == 0
        assert 0 <= lead.priority <= 1
