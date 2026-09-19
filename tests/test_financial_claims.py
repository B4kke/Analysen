"""Pure tests for the deterministic financial-claims mapping (AQ-019 slice)."""

import json
from typing import Any
from uuid import UUID, uuid4

from apps.api.app.repositories import claims_evidence
from apps.api.app.services import financial_claims


def _base_inputs(**overrides: Any) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "ratios": {"net_profit_margin": 0.1, "current_ratio": 2.0},
        "year_over_year": {"revenue": {"2022->2023": 0.05}},
        "auditor_notes": ["Revisor bemerker fortsatt drift."],
        "going_concern": True,
    }
    inputs.update(overrides)
    return inputs


def test_ratio_claims_shape_and_count() -> None:
    claims = financial_claims.build_financial_claims(
        **_base_inputs(year_over_year={}, auditor_notes=[], going_concern=None),
    )
    assert len(claims) == 2
    by_predicate = {claim["predicate"]: claim for claim in claims}
    assert set(by_predicate) == {
        "financial.ratio.current_ratio",
        "financial.ratio.net_profit_margin",
    }
    for claim in claims:
        assert set(claim) == {"predicate", "value", "status", "evidence_role"}
        assert claim["status"] == "SUPPORTED"
        assert claim["evidence_role"] == "SUPPORTS"
        assert set(claim["value"]) == {"value"}
        assert isinstance(claim["value"]["value"], float)
        assert claim["predicate"].startswith("financial.ratio.")
    assert by_predicate["financial.ratio.net_profit_margin"]["value"] == {"value": 0.1}


def test_yoy_claims_cover_each_period() -> None:
    yoy = {
        "revenue": {"2021->2022": 0.1, "2022->2023": -0.02},
        "net_income": {"2022->2023": 0.5},
    }
    claims = financial_claims.build_financial_claims(
        **_base_inputs(ratios={}, year_over_year=yoy, auditor_notes=[], going_concern=None),
    )
    assert len(claims) == 3
    triples = {(c["predicate"], c["value"]["period"], c["value"]["change"]) for c in claims}
    assert triples == {
        ("financial.yoy.revenue", "2021->2022", 0.1),
        ("financial.yoy.revenue", "2022->2023", -0.02),
        ("financial.yoy.net_income", "2022->2023", 0.5),
    }
    for claim in claims:
        assert claim["status"] == "SUPPORTED"
        assert claim["evidence_role"] == "SUPPORTS"


def test_auditor_notes_emit_one_claim_per_note() -> None:
    notes = ["Revisor påpeker usikkerhet.", "Auditor notes going concern risk."]
    claims = financial_claims.build_financial_claims(
        **_base_inputs(ratios={}, year_over_year={}, auditor_notes=notes, going_concern=None),
    )
    assert len(claims) == len(notes)
    assert [c["predicate"] for c in claims] == ["financial.auditor_note"] * len(notes)
    assert [c["value"] for c in claims] == [{"note": note} for note in notes]
    for claim in claims:
        assert claim["status"] == "SUPPORTED"
        assert claim["evidence_role"] == "SUPPORTS"


def test_going_concern_true_emits_exactly_one_claim() -> None:
    claims = financial_claims.build_financial_claims(
        **_base_inputs(ratios={}, year_over_year={}, auditor_notes=[], going_concern=True),
    )
    gc_claims = [c for c in claims if c["predicate"] == "financial.going_concern_discussed"]
    assert len(claims) == 1
    assert len(gc_claims) == 1
    assert gc_claims[0]["value"] == {"discussed": True}
    assert gc_claims[0]["status"] == "SUPPORTED"
    assert gc_claims[0]["evidence_role"] == "SUPPORTS"


def test_going_concern_none_emits_zero_and_no_negative_claims() -> None:
    claims = financial_claims.build_financial_claims(
        **_base_inputs(ratios={}, year_over_year={}, auditor_notes=[], going_concern=None),
    )
    assert claims == []
    serialized = json.dumps(claims, ensure_ascii=False)
    assert "not_discussed" not in serialized
    assert "not-discussed" not in serialized
    assert "no_going_concern" not in serialized
    for claim in claims:
        assert "not_discussed" not in claim["predicate"]
        value = claim["value"]
        assert not (isinstance(value, dict) and value.get("discussed") is False)


async def test_persist_maps_args_and_defaults_supports(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []
    claim_ids = [uuid4(), uuid4()]

    async def fake_upsert(
        session: Any,
        investigation_id: UUID,
        subject_entity_id: UUID | None,
        predicate: str,
        value: Any,
        status: str,
        evidence_ids: list[UUID],
        evidence_role: str = "SUPPORTS",
    ) -> UUID:
        calls.append(
            {
                "session": session,
                "investigation_id": investigation_id,
                "subject_entity_id": subject_entity_id,
                "predicate": predicate,
                "value": value,
                "status": status,
                "evidence_ids": evidence_ids,
                "evidence_role": evidence_role,
            }
        )
        return claim_ids[len(calls) - 1]

    monkeypatch.setattr(claims_evidence, "upsert_claim", fake_upsert)

    session = object()
    investigation_id = uuid4()
    subject_entity_id = uuid4()
    evidence_ids = [uuid4()]
    input_claims: list[dict[str, Any]] = [
        {
            "predicate": "financial.ratio.net_profit_margin",
            "value": {"value": 0.1},
            "status": "SUPPORTED",
            # evidence_role intentionally omitted: wrapper must default it.
        },
        {
            "predicate": "financial.auditor_note",
            "value": {"note": "Revisor bemerker fortsatt drift."},
            "status": "SUPPORTED",
            "evidence_role": "SUPPORTS",
        },
    ]

    result = await financial_claims.persist_financial_claims(
        session,  # type: ignore[arg-type]
        investigation_id,
        subject_entity_id,
        input_claims,
        evidence_ids,
    )

    assert result == claim_ids
    assert len(calls) == 2
    for call, input_claim in zip(calls, input_claims, strict=True):
        assert call["session"] is session
        assert call["investigation_id"] == investigation_id
        assert call["subject_entity_id"] == subject_entity_id
        assert call["predicate"] == input_claim["predicate"]
        assert call["value"] == input_claim["value"]
        assert call["status"] == "SUPPORTED"
        assert call["evidence_ids"] == evidence_ids
        assert call["evidence_ids"] is evidence_ids
    # SUPPORTS default applies when the dict omits evidence_role.
    assert calls[0]["evidence_role"] == "SUPPORTS"
    assert calls[1]["evidence_role"] == "SUPPORTS"
