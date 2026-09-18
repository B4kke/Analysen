"""PDF extraction pipeline for document processing (AQ-018).

Text/layout extraction, table extraction, OCR fallback, and deterministic
financial analysis from PDF documents. All PDF libraries are optional:
importing this module never fails, but calling extraction without the
research dependencies raises a clear error. Pure number-crunching helpers
have no third-party dependencies so they are unit-testable anywhere.
"""

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import camelot  # type: ignore[import-not-found]
    import pdfplumber  # type: ignore[import-not-found]
    import pymupdf  # type: ignore[import-not-found]
    import pytesseract  # type: ignore[import-not-found]
    import tabula  # type: ignore[import-not-found]
    from PIL import Image  # type: ignore[import-not-found]

try:
    import pdfplumber

    _PDFPLUMBER_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    pdfplumber = None
    _PDFPLUMBER_AVAILABLE = False

try:
    import pymupdf

    _PYMUPDF_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    pymupdf = None
    _PYMUPDF_AVAILABLE = False

try:
    from PIL import Image

    _PIL_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    Image = None
    _PIL_AVAILABLE = False

try:
    import pytesseract

    _TESSERACT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    pytesseract = None
    _TESSERACT_AVAILABLE = False

try:
    import camelot

    _CAMELOT_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    camelot = None
    _CAMELOT_AVAILABLE = False

try:
    import tabula

    _TABULA_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    tabula = None
    _TABULA_AVAILABLE = False


class PdfDependenciesMissing(RuntimeError):
    """Raised when extraction is attempted without the research PDF stack."""


def _require_pdf_stack() -> None:
    if not (_PDFPLUMBER_AVAILABLE and _PYMUPDF_AVAILABLE):
        raise PdfDependenciesMissing(
            "PDF extraction needs the research dependencies: "
            "pip install -r requirements-research.lock"
        )


_NUMBER_CLEANUP = re.compile(r"[^\d,.\-()%]")
_YEAR_PATTERN = re.compile(r"\b(19\d{2}|20\d{2})\b")


def parse_number(raw: Any) -> float | None:
    """Parse Norwegian/English formatted numbers deterministically.

    Handles "1 234,56" -> 1234.56, "1,234.56" -> 1234.56, "(123)" -> -123.0,
    "12 %" -> 0.12. Returns None when no number is present.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = _NUMBER_CLEANUP.sub("", str(raw).replace("\u00a0", " ").strip())
    if not text or text in {"-", "(", ")", "( )"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    percent = False
    if text.endswith("%"):
        percent = True
        text = text[:-1]
    # Decide decimal separator: the rightmost of ',' and '.' wins.
    last_comma = text.rfind(",")
    last_dot = text.rfind(".")
    if last_comma > last_dot:
        text = text.replace(".", "").replace(",", ".")
    elif last_dot > last_comma:
        text = text.replace(",", "")
    text = text.replace(" ", "")
    try:
        value = float(text)
    except ValueError:
        return None
    if negative:
        value = -value
    if percent:
        value = value / 100.0
    return value


# Canonical financial figure keys mapped from Norwegian and English labels.
FIGURE_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("net_income", ("net income", "nettoinntekt", "årsresultat", "net profit")),
    ("revenue", ("revenue", "omsetning", "sales", "driftsinntekter", "total income")),
    ("operating_income", ("operating income", "driftsresultat", "ebit", "operating profit")),
    ("ebitda", ("ebitda",)),
    ("current_assets", ("current assets", "omløpsmidler")),
    ("current_liabilities", ("current liabilities", "kortsiktig gjeld")),
    ("cash", ("cash", "kontanter", "bankinnskudd", "cash and cash equivalents")),
    ("total_equity", ("total equity", "egenkapital", "sum egenkapital")),
    ("total_assets", ("total assets", "sum eiendeler", "total capital")),
    ("total_debt", ("total debt", "sum gjeld", "total liabilities")),
)


def _match_figure_key(label: str) -> str | None:
    normalized = label.strip().casefold()
    for key, aliases in FIGURE_LABELS:
        if any(alias in normalized for alias in aliases):
            return key
    return None


def extract_key_figures(tables: list[list[list[str]]]) -> dict[str, float]:
    """Extract canonical financial figures from raw tables.

    Later tables win on duplicate keys; unparseable cells are skipped.
    """
    figures: dict[str, float] = {}
    for table in tables:
        for row in table:
            if len(row) < 2 or not row[0]:
                continue
            key = _match_figure_key(str(row[0]))
            if key is None:
                continue
            value = parse_number(row[1])
            if value is not None:
                figures[key] = value
    return figures


def compute_financial_ratios(figures: dict[str, float]) -> dict[str, float]:
    """Compute deterministic financial ratios; never divides by zero."""
    ratios: dict[str, float] = {}

    def safe_div(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator is None or denominator == 0:
            return None
        return numerator / denominator

    pairs: tuple[tuple[str, str, str], ...] = (
        ("net_profit_margin", "net_income", "revenue"),
        ("operating_margin", "operating_income", "revenue"),
        ("ebitda_margin", "ebitda", "revenue"),
        ("current_ratio", "current_assets", "current_liabilities"),
        ("cash_ratio", "cash", "current_liabilities"),
        ("equity_ratio", "total_equity", "total_assets"),
        ("debt_to_equity", "total_debt", "total_equity"),
        ("asset_turnover", "revenue", "total_assets"),
    )
    for name, num_key, den_key in pairs:
        value = safe_div(figures.get(num_key), figures.get(den_key))
        if value is not None:
            ratios[name] = value
    return ratios


def extract_yearly_data(
    tables: list[list[list[str]]],
) -> dict[str, dict[int, float]]:
    """Extract per-year series from tables whose header row holds years."""
    yearly: dict[str, dict[int, float]] = {}
    for table in tables:
        if len(table) < 2:
            continue
        # Skip first column (label column) when detecting year headers
        header_years = [_YEAR_PATTERN.search(str(cell or "")) for cell in table[0][1:]]
        years = [int(match.group(1)) if match else None for match in header_years]
        if sum(1 for year in years if year is not None) < 2:
            continue
        for row in table[1:]:
            if not row or not row[0]:
                continue
            label = str(row[0]).strip()
            for index, year in enumerate(years):
                if year is None or index + 1 >= len(row):
                    continue
                value = parse_number(row[index + 1])
                if value is not None:
                    yearly.setdefault(label, {})[year] = value
    return yearly


def compute_year_over_year(
    yearly: dict[str, dict[int, float]],
) -> dict[str, dict[str, float]]:
    """Compute relative change between consecutive years per metric."""
    result: dict[str, dict[str, float]] = {}
    for metric, series in yearly.items():
        ordered = sorted(series.items())
        changes: dict[str, float] = {}
        for (prev_year, prev_value), (year, value) in zip(ordered, ordered[1:], strict=False):
            if prev_value != 0:
                changes[f"{prev_year}->{year}"] = (value - prev_value) / abs(prev_value)
        if changes:
            result[metric] = changes
    return result


_AUDIT_KEYWORDS = (
    "auditor",
    "revisor",
    "revisjonsberetning",
    "going concern",
    "gående foretak",
    "forutsetningen om fortsatt drift",
)


def extract_auditor_notes(text: str) -> list[str]:
    """Return distinct sentences mentioning auditors or going concern."""
    notes: list[str] = []
    for sentence in re.split(r"[.!?\n]", text):
        cleaned = sentence.strip()
        if cleaned and any(keyword in cleaned.casefold() for keyword in _AUDIT_KEYWORDS):
            notes.append(cleaned)
    return list(dict.fromkeys(notes))


def detect_going_concern(text: str) -> bool | None:
    """True when going concern is discussed; None when never mentioned."""
    lowered = text.casefold()
    if "going concern" in lowered or "fortsatt drift" in lowered or "gående foretak" in lowered:
        return True
    return None


@dataclass(frozen=True)
class ExtractedPage:
    page_number: int
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[ExtractedPage]
    metadata: dict[str, Any]
    sha256: str
    ratios: dict[str, float] = field(default_factory=dict)
    year_over_year: dict[str, dict[str, float]] = field(default_factory=dict)
    auditor_notes: list[str] = field(default_factory=list)
    going_concern: bool | None = None


class PDFExtractionPipeline:
    """Byte-level PDF extraction with deterministic financial analysis."""

    def __init__(
        self,
        *,
        extract_tables: bool = True,
        ocr_fallback: bool = True,
        ocr_language: str = "nor+eng",
    ) -> None:
        self.extract_tables = extract_tables
        self.ocr_fallback = ocr_fallback
        self.ocr_language = ocr_language

    def extract(self, pdf_bytes: bytes) -> ExtractedDocument:
        """Extract text, tables and financials; OCR fallback for scanned pages."""
        _require_pdf_stack()
        assert pdfplumber is not None and pymupdf is not None
        digest = hashlib.sha256(pdf_bytes).hexdigest()

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [self._extract_page(page, number) for number, page in enumerate(pdf.pages, 1)]

        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            metadata = dict(doc.metadata or {})

        full_text = "\n".join(page.text for page in pages)
        if self.ocr_fallback and not full_text.strip():
            full_text = "\n".join(self._ocr_pages(pdf_bytes))
            pages = [
                ExtractedPage(page_number=number, text=text)
                for number, text in enumerate(full_text.split("\f"), 1)
            ] if full_text.strip() else pages

        tables = [table for page in pages for table in page.tables]
        figures = extract_key_figures(tables)
        return ExtractedDocument(
            pages=pages,
            metadata=metadata,
            sha256=digest,
            ratios=compute_financial_ratios(figures),
            year_over_year=compute_year_over_year(extract_yearly_data(tables)),
            auditor_notes=extract_auditor_notes(full_text),
            going_concern=detect_going_concern(full_text),
        )

    def _extract_page(self, page: Any, page_number: int) -> ExtractedPage:
        text = page.extract_text() or ""
        tables: list[list[list[str]]] = []
        if self.extract_tables:
            try:
                tables = [
                    [[str(cell or "") for cell in row] for row in table]
                    for table in (page.extract_tables() or [])
                ]
            except Exception:
                tables = []
        return ExtractedPage(page_number=page_number, text=text, tables=tables)

    def _ocr_pages(self, pdf_bytes: bytes) -> list[str]:
        """Render pages and OCR them; empty list when the stack is missing."""
        if not (self.ocr_fallback and _TESSERACT_AVAILABLE and _PIL_AVAILABLE):
            return []
        assert pymupdf is not None and pytesseract is not None and Image is not None
        texts: list[str] = []
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            for page in doc:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                texts.append(pytesseract.image_to_string(image, lang=self.ocr_language))
        return texts

    def extract_tables_camelot(self, pdf_bytes: bytes) -> list[list[list[str]]]:
        """Lattice/stream table extraction; empty when Camelot is missing."""
        if not _CAMELOT_AVAILABLE:
            return []
        assert camelot is not None
        try:
            found = camelot.read_pdf(io.BytesIO(pdf_bytes), pages="all", flavor="lattice")
            return [[[str(cell) for cell in row] for row in table.data] for table in found]
        except Exception:
            return []

    def extract_tables_tabula(self, pdf_bytes: bytes) -> list[list[list[str]]]:
        """Tabula table extraction; empty when Tabula/Java is missing."""
        if not _TABULA_AVAILABLE:
            return []
        assert tabula is not None
        try:
            frames = tabula.read_pdf(io.BytesIO(pdf_bytes), pages="all", multiple_tables=True)
            tables: list[list[list[str]]] = []
            for frame in frames:
                tables.append(
                    [[str(value) for value in row] for row in frame.values.tolist()]
                )
            return tables
        except Exception:
            return []


def extract_pdf_document(pdf_bytes: bytes, **kwargs: Any) -> ExtractedDocument:
    """Convenience wrapper around PDFExtractionPipeline."""
    return PDFExtractionPipeline(**kwargs).extract(pdf_bytes)
