"""Typed extraction from lawful NB article context (AQ-031).

Pure functions: no network, no LLM. Operates on already-fetched context text
(DH-lab concordance, permitted OCR crop, or public web article) to produce
structured candidates for the verifier pipeline. Does not call models.

The permitted page-image pipeline in this module implements
docs/NATIONAL_LIBRARY.md "Permitted page/image extraction":

1. page bytes are hashed (page_sha256) before any derived processing,
2. the page is OCRed with Norwegian language data (``lang="nor"``),
3. IIIF ``xywh`` anchors seed the article-region search,
4. the region is expanded conservatively and clamped to the page,
5. the crop is re-OCRed and the target must still be present (validated),
6. every derived crop records parent page URN, exact crop geometry and
   both hashes.

OCR and image backends are injectable: production uses Pillow +
pytesseract (``requirements-research.txt``); tests inject fakes so CI never
needs the native stack. Raw-byte persistence stays with the caller
(executor raw store), which also owns the rights gate: nothing here fetches
bytes or decides access.
"""

import contextlib
import hashlib
import io
import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.domain.nb_media import NBTextAvailability
from apps.api.app.services.nb_article_locator import parse_xywh


class NBExtractedArticle(BaseModel):
    """Structured extraction from a lawful article text/crop/context."""

    model_config = ConfigDict(extra="forbid")

    headline: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=2000)
    target_context: str | None = Field(default=None, max_length=5000)
    persons: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    dates: list[date] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    caption: str | None = Field(default=None, max_length=2000)
    claim_candidates: list[str] = Field(default_factory=list)
    text_availability: NBTextAvailability = NBTextAvailability.UNAVAILABLE


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return cleaned[:limit]


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in text.split("\n") if line.strip()]


def _first_nonempty(lines: list[str]) -> str | None:
    for line in lines:
        if line:
            return line
    return None


def _extract_persons(text: str) -> list[str]:
    """Heuristic person extraction from Norwegian text (no LLM, conservative).

    Looks for capitalized names in typical Norwegian newspaper patterns.
    This is a suggestion for verifier, not evidence.
    """
    # Pattern: "Forename Surname" or "Surname, Forename" or titles + name
    # Conservative: only 2-3 word capitalized sequences
    candidates = re.findall(
        r"\b(?:[A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ][a-zæøå]+){1,2})\b", text
    )
    # Filter out common false positives
    stopwords = {
        "Norge",
        "Oslo",
        "Bergen",
        "Trondheim",
        "Stavanger",
        "Tromsø",
        "Aftenposten",
        "VG",
        "Dagbladet",
        "NRK",
        "TV2",
        "I",
        "Og",
        "For",
        "Som",
        "På",
        "Av",
        "Til",
        "Fra",
        "Med",
        "Eller",
        "Men",
        "Denne",
        "Det",
        "Er",
        "Var",
        "Har",
        "Ble",
        "Får",
        "Så",
        "Om",
        "At",
        "En",
        "Et",
        "De",
        "Den",
        "Sitt",
        "Sin",
        "Sine",
    }
    seen = set()
    result = []
    for c in candidates:
        parts = c.split()
        if len(parts) < 2 or len(parts) > 3:
            continue
        if any(p in stopwords for p in parts):
            continue
        norm = " ".join(parts)
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result[:10]


def _extract_organizations(text: str) -> list[str]:
    """Heuristic org extraction (no LLM)."""
    # Look for AS, ASA, AS, KS, NUF, etc. and common org patterns
    candidates = re.findall(
        r"\b([A-ZÆØÅ][A-Za-zÆØÅæøå0-9&.\-]*(?:\s+[A-ZÆØÅ][A-Za-zÆØÅæøå0-9&.\-]*)*)\s+(?:AS|ASA|AS|KS|NUF|ANS|DA|SA|RF|FLI)\b",
        text,
    )
    # Also look for quoted org names
    quoted = re.findall(r'"([^"]{3,80})"', text)
    seen = set()
    result = []
    for c in candidates + quoted:
        if len(c) > 80:
            continue
        norm = c.strip()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result[:10]


def _extract_places(text: str) -> list[str]:
    """Heuristic place extraction (no LLM)."""
    # Common Norwegian place name patterns
    candidates = re.findall(
        r"\b(?:i|på|til|fra|ved|over|under)\s+([A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ][a-zæøå]+)?)\b",
        text,
    )
    seen = set()
    result = []
    for c in candidates:
        norm = c.strip()
        if len(norm) > 50:
            continue
        if norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result[:10]


def _extract_dates(text: str) -> list[date]:
    """Extract dates from text (no LLM)."""
    found: list[date] = []
    # ISO dates
    for match in re.finditer(r"\b(\d{4}-\d{2}-\d{2})\b", text):
        with contextlib.suppress(ValueError):
            found.append(datetime.strptime(match.group(1), "%Y-%m-%d").date())
    # Norwegian format: DD. MMMM YYYY or DD. MM. YYYY
    months = {
        "januar": 1,
        "februar": 2,
        "mars": 3,
        "april": 4,
        "mai": 5,
        "juni": 6,
        "juli": 7,
        "august": 8,
        "september": 9,
        "oktober": 10,
        "november": 11,
        "desember": 12,
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "okt": 10,
        "nov": 11,
        "des": 12,
    }
    for match in re.finditer(
        r"\b(\d{1,2})\.\s*([A-Za-zæøåÆØÅ]+)\s+(\d{4})\b", text, re.IGNORECASE
    ):
        with contextlib.suppress(ValueError, KeyError):
            day = int(match.group(1))
            month_str = match.group(2).lower()
            year = int(match.group(3))
            month = months.get(month_str[:3])
            if month:
                found.append(date(year, month, day))
    # Deduplicate
    seen = set()
    result = []
    for d in found:
        key = d.isoformat()
        if key not in seen:
            seen.add(key)
            result.append(d)
    return result[:10]


def _extract_roles(text: str) -> list[str]:
    """Extract role keywords from text."""
    role_keywords = [
        "styreleder",
        "nestleder",
        "styremedlem",
        "daglig leder",
        "administrerende direktør",
        "konsernsjef",
        "sjef",
        "leder",
        "direktør",
        "rådgiver",
        "konsulent",
        "eier",
        "aksjonær",
        "investor",
        "gründer",
        "medgründer",
        "formann",
        "varselformann",
        "tillitsvalgt",
    ]
    found = []
    lower = text.lower()
    for kw in role_keywords:
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            found.append(kw)
    return found


def _extract_caption(text: str) -> str | None:
    """Try to find a caption-like line (short, descriptive)."""
    lines = _split_lines(text)
    for line in lines:
        if 20 <= len(line) <= 200 and not line.endswith("."):
            return line
    return None


def _extract_claim_candidates(text: str) -> list[str]:
    """Extract potential claim-like sentences (conservative)."""
    # Split on sentence boundaries, look for factual assertions
    sentences = re.split(r"[.!?]\s+", text)
    candidates = []
    verb_pattern = r"\b(er|var|ble|har|fikk|gikk|kom|sa|meldte|påstod|bekreftet)\b"
    for s in sentences:
        s = s.strip()
        if 30 <= len(s) <= 500 and re.search(verb_pattern, s, re.IGNORECASE):
            candidates.append(s)
    return candidates[:5]


def extract_nb_article(
    context_text: str | None,
    *,
    text_availability: NBTextAvailability,
    target_name: str | None = None,
) -> NBExtractedArticle:
    """Typed extraction from already-fetched lawful context.

    Args:
        context_text: The lawful text to extract from (DH-lab concordance, OCR crop, etc.)
        text_availability: Declared availability state of the source text.
        target_name: Optional target name to anchor target_context around.

    Returns:
        Structured extraction candidates for verifier pipeline.
        LLM is NOT called here; output is suggestions only.
    """
    if not context_text or not context_text.strip():
        return NBExtractedArticle(text_availability=text_availability)

    text = " ".join(context_text.split())
    lines = _split_lines(context_text)

    # Headline: first substantial line
    headline = _first_nonempty([line for line in lines if len(line) > 15])

    # Summary: first 2-3 substantial lines combined
    substantial = [line for line in lines if len(line) > 20]
    summary = " ".join(substantial[:3]) if substantial else None

    # Target context: window around target name if provided
    target_context = None
    if target_name and target_name.lower() in text.lower():
        idx = text.lower().index(target_name.lower())
        start = max(0, idx - 200)
        end = min(len(text), idx + len(target_name) + 300)
        target_context = text[start:end]

    # Heuristic entity/date/role extraction (suggestions only)
    persons = _extract_persons(text)
    organizations = _extract_organizations(text)
    places = _extract_places(text)
    dates = _extract_dates(text)
    roles = _extract_roles(text)
    caption = _extract_caption(text)
    claim_candidates = _extract_claim_candidates(text)

    return NBExtractedArticle(
        headline=_truncate(headline, 1000),
        summary=_truncate(summary, 2000),
        target_context=_truncate(target_context, 5000),
        persons=persons,
        organizations=organizations,
        places=places,
        dates=dates,
        roles=roles,
        caption=_truncate(caption, 2000),
        claim_candidates=claim_candidates,
        text_availability=text_availability,
    )


def enrich_media_mention_with_extraction(
    mention: Any,
    context_text: str | None,
    *,
    text_availability: NBTextAvailability,
    target_name: str | None = None,
) -> dict[str, Any]:
    """Convenience: produce a dict of enriched fields for MediaMentionCandidate.

    Does not mutate the input; returns new field values for persistence.
    """
    extracted = extract_nb_article(
        context_text,
        text_availability=text_availability,
        target_name=target_name,
    )
    return {
        "headline": extracted.headline,
        "summary": extracted.summary,
        "target_context": extracted.target_context,
        "persons": extracted.persons,
        "organizations": extracted.organizations,
        "places": extracted.places,
        "dates": [d.isoformat() for d in extracted.dates],
        "roles": extracted.roles,
        "caption": extracted.caption,
        "claim_candidates": extracted.claim_candidates,
        "text_availability": extracted.text_availability.value,
    }


# ---------------------------------------------------------------------------
# Permitted page-image pipeline: anchored article-region extraction.
#
# Callers must invoke this only after the item-level rights gate explicitly
# allows derived crops (``allow_derived_crop``). Restricted items never reach
# here: the executor's fetch gate raises before any downloader runs.
# ---------------------------------------------------------------------------

NORWEGIAN_OCR_LANG = "nor"

# Conservative v1 region expansion around the anchored seed box, expressed as
# ratios of the seed size: headlines usually sit just above the hit and the
# body continues below it. Documented heuristic, not layout truth.
_REGION_EXPAND_LEFT_RATIO = 0.5
_REGION_EXPAND_RIGHT_RATIO = 0.5
_REGION_EXPAND_UP_RATIO = 1.0
_REGION_EXPAND_DOWN_RATIO = 2.0

MAX_CROP_TEXT_CHARS = 5000


class NBExtractError(Exception):
    """Typed permitted-extraction failure (never a raw backend exception)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NBOcrWord(BaseModel):
    """One OCR word in page-pixel coordinates (Norwegian OCR output)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    confidence: float = Field(default=0.0, ge=-100.0, le=100.0)


class NBArticleRegion(BaseModel):
    """Exact geometry of one derived article crop on its parent page.

    ``parent_page_urn`` plus ``(x, y, w, h)`` in page pixels identify the
    crop; ``page_sha256``/``crop_sha256`` bind it to immutable raw bytes.
    """

    model_config = ConfigDict(extra="forbid")

    parent_page_urn: str = Field(min_length=1, max_length=500)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)
    page_width: int = Field(ge=1)
    page_height: int = Field(ge=1)
    anchor_xywh: str | None = Field(default=None, max_length=100)
    page_sha256: str | None = Field(default=None, max_length=64)
    crop_sha256: str | None = Field(default=None, max_length=64)
    crop_storage_key: str | None = Field(default=None, max_length=500)
    target_validated: bool = False


class NBPermittedExtraction(BaseModel):
    """One validated article-region extraction from a permitted page."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    page_urn: str = Field(min_length=1, max_length=500)
    page_sha256: str = Field(min_length=64, max_length=64)
    page_width: int = Field(ge=1)
    page_height: int = Field(ge=1)
    region: NBArticleRegion
    crop_bytes: bytes = Field(min_length=1)
    crop_text: str | None = Field(default=None, max_length=MAX_CROP_TEXT_CHARS)
    target_validated: bool = False


PageOcrFn = Callable[[bytes], list[NBOcrWord]]
"""Injectable Norwegian word-OCR backend: image bytes -> words in pixels."""


def _normalize_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^0-9a-zæøå]+", value.lower()) if len(token) >= 2]


def _union_box(boxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[0] + box[2] for box in boxes)
    y1 = max(box[1] + box[3] for box in boxes)
    return x0, y0, x1 - x0, y1 - y0


def find_article_region(
    *,
    parent_page_urn: str,
    page_width: int,
    page_height: int,
    anchor_xywh: list[str],
    ocr_words: list[NBOcrWord],
    target_expression: str,
) -> NBArticleRegion:
    """Locate the probable article region anchored on IIIF ``xywh`` hits.

    Seed boxes come from parsed ``xywh`` anchors plus OCR words matching the
    target tokens; the union is expanded conservatively and clamped to the
    page. Pure and deterministic. Raises :class:`NBExtractError` with
    ``target_not_found`` when neither anchors nor OCR words locate the
    target, or ``invalid_geometry`` on unusable input.
    """
    cleaned_urn = (parent_page_urn or "").strip()
    if not cleaned_urn:
        raise NBExtractError("invalid_geometry", "article region requires a parent page urn")
    if page_width < 1 or page_height < 1:
        raise NBExtractError("invalid_geometry", "article region requires page dimensions")
    tokens = _normalize_tokens(target_expression or "")
    if not tokens:
        raise NBExtractError("invalid_target", "article region requires a target expression")

    seed_boxes: list[tuple[int, int, int, int]] = []
    primary_anchor: str | None = None
    for raw_anchor in anchor_xywh or []:
        parsed = parse_xywh(raw_anchor)
        if parsed is None:
            continue
        x, y, w, h = parsed
        if x + w > page_width or y + h > page_height:
            continue
        seed_boxes.append(parsed)
        if primary_anchor is None:
            primary_anchor = f"xywh={x},{y},{w},{h}"

    token_set = set(tokens)
    for word in ocr_words or []:
        in_bounds = word.x + word.w <= page_width and word.y + word.h <= page_height
        if word.text.lower() in token_set and in_bounds:
            seed_boxes.append((word.x, word.y, word.w, word.h))

    if not seed_boxes:
        raise NBExtractError(
            "target_not_found",
            "neither xywh anchors nor OCR words locate the target on the page",
        )

    seed_x, seed_y, seed_w, seed_h = _union_box(seed_boxes)
    x0 = max(0, seed_x - int(seed_w * _REGION_EXPAND_LEFT_RATIO))
    y0 = max(0, seed_y - int(seed_h * _REGION_EXPAND_UP_RATIO))
    x1 = min(page_width, seed_x + seed_w + int(seed_w * _REGION_EXPAND_RIGHT_RATIO))
    y1 = min(page_height, seed_y + seed_h + int(seed_h * _REGION_EXPAND_DOWN_RATIO))
    region_w, region_h = x1 - x0, y1 - y0
    if region_w < 1 or region_h < 1:
        raise NBExtractError("invalid_geometry", "expanded article region is empty")
    return NBArticleRegion(
        parent_page_urn=cleaned_urn,
        x=x0,
        y=y0,
        w=region_w,
        h=region_h,
        page_width=page_width,
        page_height=page_height,
        anchor_xywh=primary_anchor,
    )


def crop_page_image(page_bytes: bytes, region: NBArticleRegion) -> bytes:
    """Crop exact page pixels for a region; deterministic PNG output.

    Raises :class:`NBExtractError` (``pillow_unavailable`` / ``invalid_image``
    / ``invalid_region``) instead of leaking backend exceptions.
    """
    if not isinstance(page_bytes, (bytes, bytearray)) or not bytes(page_bytes):
        raise NBExtractError("invalid_image", "article crop requires page image bytes")
    if (
        region.x + region.w > region.page_width
        or region.y + region.h > region.page_height
    ):
        raise NBExtractError("invalid_region", "article region exceeds its parent page")
    try:
        from PIL import Image
    except ImportError as exc:
        raise NBExtractError(
            "pillow_unavailable", "article crop requires the Pillow runtime"
        ) from exc
    try:
        with Image.open(io.BytesIO(bytes(page_bytes))) as image:
            width, height = image.size
            if width != region.page_width or height != region.page_height:
                raise NBExtractError(
                    "invalid_region",
                    "article region page size does not match the page image",
                )
            cropped = image.convert("RGB").crop(
                (region.x, region.y, region.x + region.w, region.y + region.h)
            )
            buffer = io.BytesIO()
            cropped.save(buffer, format="PNG")
            return buffer.getvalue()
    except NBExtractError:
        raise
    except Exception as exc:
        raise NBExtractError(
            "invalid_image", f"page image cannot be cropped: {type(exc).__name__}"
        ) from exc


def page_image_size(page_bytes: bytes) -> tuple[int, int]:
    """Return ``(width, height)`` page pixels; typed error when unreadable."""
    if not isinstance(page_bytes, (bytes, bytearray)) or not bytes(page_bytes):
        raise NBExtractError("invalid_image", "page sizing requires page image bytes")
    try:
        from PIL import Image
    except ImportError as exc:
        raise NBExtractError(
            "pillow_unavailable", "page sizing requires the Pillow runtime"
        ) from exc
    try:
        with Image.open(io.BytesIO(bytes(page_bytes))) as image:
            return int(image.size[0]), int(image.size[1])
    except Exception as exc:
        raise NBExtractError(
            "invalid_image", f"page image cannot be read: {type(exc).__name__}"
        ) from exc


def tesseract_ocr_words_norwegian(image_bytes: bytes) -> list[NBOcrWord]:
    """Default word-OCR backend: pytesseract ``image_to_data(lang="nor")``.

    Raises :class:`NBExtractError` (``ocr_unavailable`` / ``ocr_failed``)
    when the native stack is missing or fails; callers treat that as
    "crop skipped", never as a bypass.
    """
    if not isinstance(image_bytes, (bytes, bytearray)) or not bytes(image_bytes):
        raise NBExtractError("invalid_image", "Norwegian OCR requires image bytes")
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image
    except ImportError as exc:
        raise NBExtractError(
            "ocr_unavailable", "Norwegian OCR requires the tesseract runtime"
        ) from exc
    try:
        with Image.open(io.BytesIO(bytes(image_bytes))) as image:
            data = pytesseract.image_to_data(
                image, lang=NORWEGIAN_OCR_LANG, output_type=pytesseract.Output.DICT
            )
    except NBExtractError:
        raise
    except Exception as exc:
        raise NBExtractError(
            "ocr_failed", f"Norwegian OCR failed: {type(exc).__name__}"
        ) from exc
    words: list[NBOcrWord] = []
    texts = data.get("text") or []
    count = len(texts)
    for index in range(count):
        text = str(texts[index] or "").strip()
        if not text:
            continue
        try:
            words.append(
                NBOcrWord(
                    text=text[:500],
                    x=max(0, int(data["left"][index])),
                    y=max(0, int(data["top"][index])),
                    w=max(1, int(data["width"][index])),
                    h=max(1, int(data["height"][index])),
                    confidence=float(data.get("conf", [0.0])[index] or 0.0),
                )
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return words


def extract_permitted_article(
    page_bytes: bytes,
    *,
    page_urn: str,
    anchor_xywh: list[str],
    target_expression: str,
    page_ocr_fn: PageOcrFn | None = None,
    crop_ocr_fn: PageOcrFn | None = None,
) -> NBPermittedExtraction:
    """Page bytes -> anchored region -> crop -> Norwegian OCR -> validation.

    Only call after the rights gate allows derived crops. Returns the crop
    bytes, both hashes and the parent-bound geometry; ``target_validated``
    is True only when the target expression still occurs in the crop OCR.
    Raises :class:`NBExtractError` for unusable input, missing backends or
    an unlocatable target.
    """
    cleaned_urn = (page_urn or "").strip()
    if not cleaned_urn:
        raise NBExtractError("invalid_page_urn", "permitted extraction requires a page urn")
    if not isinstance(page_bytes, (bytes, bytearray)) or not bytes(page_bytes):
        raise NBExtractError("invalid_image", "permitted extraction requires page bytes")
    tokens = _normalize_tokens(target_expression or "")
    if not tokens:
        raise NBExtractError("invalid_target", "permitted extraction requires a target expression")
    if not anchor_xywh:
        raise NBExtractError("missing_anchor", "permitted extraction requires xywh anchors")

    raw_page = bytes(page_bytes)
    page_sha256 = hashlib.sha256(raw_page).hexdigest()
    page_width, page_height = page_image_size(raw_page)

    page_backend = page_ocr_fn or tesseract_ocr_words_norwegian
    try:
        page_words = list(page_backend(raw_page))
    except NBExtractError:
        raise
    except Exception as exc:
        raise NBExtractError(
            "ocr_failed", f"page OCR failed: {type(exc).__name__}"
        ) from exc

    region = find_article_region(
        parent_page_urn=cleaned_urn,
        page_width=page_width,
        page_height=page_height,
        anchor_xywh=list(anchor_xywh),
        ocr_words=page_words,
        target_expression=target_expression,
    )
    region.page_sha256 = page_sha256

    crop_bytes = crop_page_image(raw_page, region)
    region.crop_sha256 = hashlib.sha256(crop_bytes).hexdigest()

    crop_backend = crop_ocr_fn or page_ocr_fn or tesseract_ocr_words_norwegian
    try:
        crop_words = list(crop_backend(crop_bytes))
    except NBExtractError:
        raise
    except Exception as exc:
        raise NBExtractError(
            "ocr_failed", f"crop OCR failed: {type(exc).__name__}"
        ) from exc
    crop_text = _truncate(" ".join(word.text for word in crop_words), MAX_CROP_TEXT_CHARS)
    normalized_crop = (crop_text or "").lower()
    validated = all(token in normalized_crop for token in tokens)
    region.target_validated = validated
    return NBPermittedExtraction(
        page_urn=cleaned_urn,
        page_sha256=page_sha256,
        page_width=page_width,
        page_height=page_height,
        region=region,
        crop_bytes=crop_bytes,
        crop_text=crop_text,
        target_validated=validated,
    )