"""Unit tests for the deterministic PDF-analysis helpers (AQ-018).

Only pure functions are tested here: number parsing, figure extraction,
ratios, year-over-year series, auditor notes and going-concern detection.
Byte-level extraction needs the research PDF stack and is covered by the
dependency-guard test below.
"""

import pytest

from apps.api.app.services import pdf_extraction
from apps.api.app.services.pdf_extraction import (
    PdfDependenciesMissing,
    compute_financial_ratios,
    compute_year_over_year,
    detect_going_concern,
    extract_auditor_notes,
    extract_key_figures,
    extract_yearly_data,
    parse_number,
)


def test_parse_number_norwegian_format() -> None:
    assert parse_number("1 234,56") == 1234.56
    assert parse_number("12 345 678") == 12345678.0


def test_parse_number_english_format() -> None:
    assert parse_number("1,234.56") == 1234.56
    assert parse_number("1234.5") == 1234.5


def test_parse_number_accounting_negatives_and_percent() -> None:
    assert parse_number("(123)") == -123.0
    assert parse_number("12,5 %") == 0.125
    assert parse_number("-42") == -42.0


def test_parse_number_invalid_returns_none() -> None:
    assert parse_number(None) is None
    assert parse_number("") is None
    assert parse_number("aksjer") is None
    assert parse_number("-") is None


def test_parse_number_passthrough_numeric() -> None:
    assert parse_number(7) == 7.0
    assert parse_number(2.5) == 2.5


def test_extract_key_figures_norwegian_labels() -> None:
    tables = [
        [["Omsetning", "10 000"], ["Driftsresultat", "1 500"], ["Egenkapital", "4 000"]],
        [["Sum eiendeler", "8 000"], ["Årsresultat", "900"]],
    ]
    figures = extract_key_figures(tables)
    assert figures == {
        "revenue": 10000.0,
        "operating_income": 1500.0,
        "total_equity": 4000.0,
        "total_assets": 8000.0,
        "net_income": 900.0,
    }


def test_extract_key_figures_english_labels_and_later_wins() -> None:
    tables = [
        [["Revenue", "1000"], ["Revenue", "2000"], ["Gibberish metric", "5"]],
        [["Cash", "(50)"], ["No value row", ""]],
    ]
    figures = extract_key_figures(tables)
    assert figures["revenue"] == 2000.0
    assert figures["cash"] == -50.0
    assert "gibberish metric" not in figures
    assert len(figures) == 2


def test_compute_financial_ratios_valid() -> None:
    figures = {
        "revenue": 10000.0,
        "net_income": 800.0,
        "operating_income": 1200.0,
        "ebitda": 2000.0,
        "current_assets": 3000.0,
        "current_liabilities": 1500.0,
        "cash": 500.0,
        "total_equity": 4000.0,
        "total_assets": 8000.0,
        "total_debt": 4000.0,
    }
    ratios = compute_financial_ratios(figures)
    assert ratios["net_profit_margin"] == pytest.approx(0.08)
    assert ratios["operating_margin"] == pytest.approx(0.12)
    assert ratios["ebitda_margin"] == pytest.approx(0.2)
    assert ratios["current_ratio"] == pytest.approx(2.0)
    assert ratios["cash_ratio"] == pytest.approx(1 / 3)
    assert ratios["equity_ratio"] == pytest.approx(0.5)
    assert ratios["debt_to_equity"] == pytest.approx(1.0)
    assert ratios["asset_turnover"] == pytest.approx(1.25)


def test_compute_financial_ratios_never_divides_by_zero() -> None:
    figures = {"revenue": 0.0, "net_income": 100.0, "current_liabilities": 0.0}
    assert compute_financial_ratios(figures) == {}
    assert compute_financial_ratios({}) == {}
    # Missing numerator is skipped, present pair is computed.
    ratios = compute_financial_ratios({"revenue": 100.0, "net_income": 10.0})
    assert ratios == {"net_profit_margin": pytest.approx(0.1)}


def test_extract_yearly_data_multi_year_table() -> None:
    tables = [
        [
            ["Post", "2023", "2024"],
            ["Omsetning", "9 000", "10 000"],
            ["Driftsresultat", "1 000", "1 500"],
        ]
    ]
    yearly = extract_yearly_data(tables)
    assert yearly["Omsetning"] == {2023: 9000.0, 2024: 10000.0}
    assert yearly["Driftsresultat"] == {2023: 1000.0, 2024: 1500.0}


def test_extract_yearly_data_ignores_single_year_tables() -> None:
    tables = [[["Post", "2024"], ["Omsetning", "10 000"]]]
    assert extract_yearly_data(tables) == {}
    assert extract_yearly_data([]) == {}
    assert extract_yearly_data([[["only header"]]]) == {}


def test_compute_year_over_year() -> None:
    yearly = {"Omsetning": {2022: 8000.0, 2023: 9000.0, 2024: 10000.0}}
    result = compute_year_over_year(yearly)
    assert result["Omsetning"]["2022->2023"] == pytest.approx(0.125)
    assert result["Omsetning"]["2023->2024"] == pytest.approx(1 / 9)


def test_compute_year_over_year_skips_zero_base() -> None:
    assert compute_year_over_year({"X": {2023: 0.0, 2024: 5.0}}) == {}
    assert compute_year_over_year({"X": {2024: 5.0}}) == {}


def test_extract_auditor_notes_norwegian_and_english() -> None:
    text = (
        "Styret foreslår utbytte. Revisor har avgit revisjonsberetning uten forbehold. "
        "Driften er stabil. The auditor notes a going concern uncertainty. Været var fint."
    )
    notes = extract_auditor_notes(text)
    assert len(notes) == 2
    assert any("revisjonsberetning" in note for note in notes)
    assert any("going concern" in note for note in notes)


def test_extract_auditor_notes_deduplicates() -> None:
    text = "Revisor er uavhengig. Revisor er uavhengig."
    assert extract_auditor_notes(text) == ["Revisor er uavhengig"]


def test_detect_going_concern() -> None:
    assert detect_going_concern("Forutsetningen om fortsatt drift er lagt til grunn.") is True
    assert detect_going_concern("Going concern basis applied.") is True
    assert detect_going_concern("Resultatet var positivt.") is None


def test_extract_requires_research_stack_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(pdf_extraction, "_PDFPLUMBER_AVAILABLE", False)
    pipeline = pdf_extraction.PDFExtractionPipeline()
    with pytest.raises(PdfDependenciesMissing, match="research dependencies"):
        pipeline.extract(b"%PDF-1.4 fake")


def test_camelot_tabula_helpers_return_empty_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(pdf_extraction, "_CAMELOT_AVAILABLE", False)
    monkeypatch.setattr(pdf_extraction, "_TABULA_AVAILABLE", False)
    pipeline = pdf_extraction.PDFExtractionPipeline()
    assert pipeline.extract_tables_camelot(b"fake") == []
    assert pipeline.extract_tables_tabula(b"fake") == []
