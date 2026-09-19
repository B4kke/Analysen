"""Bounded research pass: frontier selection, trigger evaluation, execution.

One pass processes admitted PENDING leads until the frontier is empty, the
budget is spent, or the lead cap is reached. When the frontier runs dry, an
optional planner proposes new leads once per pass; every proposal still
passes the deterministic lead gate before it can run. Each lead is committed
separately so a crash resumes without double-fetch (re-execution is a no-op
for terminal leads). Leads the evaluator routes to CONTEXT_ONLY or
BLOCKED_BY_SCOPE are marked BLOCKED with the reason so the pass terminates;
they can be re-proposed later if scope changes. The planner is the only
model call in the loop.
"""

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import Lead, TargetType
from apps.api.app.domain.scope import ExpansionState, ScopeModule, TriggerType
from apps.api.app.domain.trigger_eval import FrontierLead, TriggerDecision
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.frontier import select_next
from apps.api.app.services.lead_executor import ExecutorTools, execute_lead
from apps.api.app.services.planner import (
    ChatProvider,
    PlannerContext,
    PlannerError,
    plan_next_actions,
    proposal_to_lead_payload,
)
from apps.api.app.services.trigger_evaluator import evaluate_trigger


def _to_frontier_lead(row: dict) -> FrontierLead:
    return FrontierLead(
        lead_type=row["lead_type"],
        value=row["value"],
        reason=row["reason"],
        priority=row["priority"],
        depth=row["depth"],
        originating_claim_id=row["originating_claim_id"],
        scope_area=row["scope_area"],
        trigger_type=row["trigger_type"],
        information_need=row["information_need"],
        relation_depth=row["relation_depth"],
        status=row["status"],
    )


def _pending_lead_signature(lead_type: str, scope_area: str, value: Any) -> str:
    """Canonical identity of a pending lead for cross-pass dedup."""
    canonical = json.dumps(
        {"lead_type": lead_type, "scope_area": scope_area, "value": value},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


NB_SEED_LEAD_TYPE = "nb_newspaper_search"
NB_SEED_QUERY_CLASS = "ENTITY_ALIAS_EXACT"


def _deduplicate_seed_names(names: list[str]) -> list[str]:
    """Deduplicate exact-name seed queries deterministically.

    Stripped names shorter than 3 chars are dropped. Dedup is on the
    normalized form (unidecode + casefold) so a verified alias that only
    differs by case/whitespace/diacritics from the target name never
    produces a second lead. First-seen spelling wins; order is preserved.
    """
    from apps.api.app.services.entity_resolution import normalize_name

    ordered: list[str] = []
    seen: set[str] = set()
    for raw in names:
        cleaned = (raw or "").strip()
        if len(cleaned) < 3:
            continue
        key = normalize_name(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def build_nb_seed_lead(target_name: str) -> Lead | None:
    """Build the deterministic NB exact-name seed lead, or None for no name.

    Pure constructor so the seed shape is unit-testable without a database.
    The lead always goes through propose_lead admission before it can run.
    """
    names = _deduplicate_seed_names([target_name or ""])
    if not names:
        return None
    return build_nb_seed_leads(names)[0]


def build_nb_seed_leads(names: list[str]) -> list[Lead]:
    """Build deduplicated NB exact-name seed leads for target + aliases.

    Pure constructor: every lead uses ``nb_newspaper_search`` /
    ``DIRECT_SOURCE_LOOKUP`` under ``WEB_MEDIA`` at relation depth 0.
    Verified aliases intentionally reuse ``DIRECT_SOURCE_LOOKUP`` — the
    passive ``NEW_VERIFIED_ALIAS`` trigger would park the lead as
    ``BLOCKED/passive_trigger_requires_review`` and it would never run.
    """
    leads: list[Lead] = []
    for name in _deduplicate_seed_names(list(names)):
        leads.append(
            Lead(
                lead_type=NB_SEED_LEAD_TYPE,
                value={"query": name, "query_class": NB_SEED_QUERY_CLASS},
                reason="Deterministisk NB-oppslag på investigation-target (exact-name)",
                priority=0.7,
                depth=0,
                scope_area=ScopeModule.WEB_MEDIA,
                trigger_type=TriggerType.DIRECT_SOURCE_LOOKUP,
                information_need=(
                    "Finn historisk avis-/publikasjonsomtale av target i "
                    "Nasjonalbibliotekets samling"
                ),
                relation_depth=0,
            )
        )
    return leads


async def _load_verified_alias_names(
    session: AsyncSession,
    investigation_id: UUID,
) -> list[str]:
    """Load verified (MATCH) alias spellings attached to this investigation.

    Fail-closed to ``[]``: alias seeding is best-effort and must never break
    the baseline target seed. Only ``MATCH`` entities count as verified;
    ``PROBABLE_MATCH``/``UNRESOLVED`` still require human review.
    """
    from sqlalchemy import text

    try:
        rows = (
            (
                await session.execute(
                    text("""
                        SELECT DISTINCT ea.alias AS alias
                        FROM entity_aliases ea
                        JOIN entities e ON e.id = ea.entity_id
                        JOIN investigation_entities ie ON ie.entity_id = e.id
                        WHERE ie.investigation_id = :id
                          AND e.resolution_state = 'MATCH'
                        ORDER BY ea.alias
                    """),
                    {"id": investigation_id},
                )
            )
            .mappings()
            .all()
        )
    except Exception:
        return []
    names: list[str] = []
    for row in rows:
        alias = row.get("alias")
        if isinstance(alias, str) and alias.strip():
            names.append(alias)
    return names


async def seed_nb_media_lead(
    session: AsyncSession,
    investigation_id: UUID,
    investigation: Any,
) -> int:
    """Seed deterministic NB lookup for person/company/organization targets.

    The seed never waits for the planner: an explicit non-domain target under
    an active WEB_MEDIA module always gets deduplicated exact-name
    ``nb_newspaper_search`` leads with a DIRECT_SOURCE_LOOKUP trigger — one
    for the target name plus one per verified (MATCH) alias spelling. Every
    lead passes the same deterministic admission (propose_lead) as any other
    proposal. Reruns never duplicate: identity covers every stored lead
    regardless of status, and alias spellings that normalize to an existing
    query never produce a second lead. Returns the number of lead rows
    proposed (0 when nothing new was needed).
    """
    if investigation.target.type == TargetType.DOMAIN:
        return 0
    if ScopeModule.WEB_MEDIA not in investigation.scope_modules:
        return 0
    alias_names = await _load_verified_alias_names(session, investigation_id)
    leads = build_nb_seed_leads([investigation.target.name, *alias_names])
    if not leads:
        return 0
    rows = await repository.list_lead_identity_rows(session, investigation_id)
    existing = {
        _pending_lead_signature(row["lead_type"], str(row["scope_area"]), row["value"])
        for row in rows
    }
    proposed = 0
    for lead in leads:
        signature = _pending_lead_signature(
            lead.lead_type, lead.scope_area.value, lead.value
        )
        if signature in existing:
            continue
        existing.add(signature)
        await repository.propose_lead(session, investigation_id, lead)
        proposed += 1
    if proposed:
        await session.commit()
    return proposed


async def _plan_and_admit(
    session: AsyncSession,
    investigation_id: UUID,
    investigation: Any,
    provider: ChatProvider,
    model: str,
    budget_available: bool,
) -> int:
    """Ask the planner once and admit proposals through the deterministic gate.

    Returns the number of newly admitted PENDING leads. Proposals duplicating
    any existing lead (pending or terminal) are skipped so reruns never
    multiply work; failed or refused questions are only re-proposed manually.
    Raises PlannerError when the model output is schema-invalid.
    """
    rows = await repository.list_pending_leads(session, investigation_id)
    identity_rows = await repository.list_lead_identity_rows(session, investigation_id)
    pending_signatures = {
        _pending_lead_signature(row["lead_type"], str(row["scope_area"]), row["value"])
        for row in identity_rows
    }
    open_leads = [
        {
            "lead_type": row["lead_type"],
            "scope_area": str(row["scope_area"]),
            "trigger_type": str(row["trigger_type"]),
            "information_need": row["information_need"],
        }
        for row in rows
    ]
    context = PlannerContext(
        target_type=investigation.target.type.value,
        target_name=investigation.target.name,
        scope=investigation,
        open_leads=open_leads,
        budgets={"budget_available": budget_available},
    )
    proposals = await plan_next_actions(context, provider, model=model)
    admitted = 0
    for proposal in proposals:
        payload = proposal_to_lead_payload(proposal)
        signature = _pending_lead_signature(
            payload["lead_type"], payload["scope_area"], payload["value"]
        )
        if signature in pending_signatures:
            continue
        pending_signatures.add(signature)
        _, status = await repository.propose_lead(
            session, investigation_id, Lead(**payload)
        )
        if status == "PENDING":
            admitted += 1
    await session.commit()
    return admitted


async def _run_research_pass(
    session: AsyncSession,
    investigation_id: UUID,
    tools: ExecutorTools,
    *,
    max_leads: int = 10,
    budget_available: bool = True,
    job_id: UUID,
    planner_provider: ChatProvider | None = None,
    planner_model: str | None = None,
) -> dict:
    """Run one bounded pass; return an audited summary dict."""
    investigation = await repository.get_investigation_record(session, investigation_id)
    # Deterministic direct-source seed first: a person target with WEB_MEDIA
    # always gets its baseline NB lookup without waiting for the planner.
    # The seed is idempotent and gated like every other proposal.
    await seed_nb_media_lead(session, investigation_id, investigation)
    executed = 0
    blocked = 0
    failed = 0
    planned = 0
    stopped_reason = ""
    attempted: set[str] = set()
    planner_called = False

    for _ in range(max(1, max_leads)):
        rows = await repository.list_pending_leads(session, investigation_id)
        pairs = [
            (row["id"], _to_frontier_lead(row)) for row in rows if str(row["id"]) not in attempted
        ]
        selected, reason = select_next(
            [lead for _, lead in pairs],
            max_depth=investigation.max_relation_depth,
            budget_available=budget_available,
        )
        if selected is None:
            if (
                reason == "no_executable_leads"
                and not planner_called
                and planner_provider is not None
                and planner_model is not None
            ):
                planner_called = True
                try:
                    planned += await _plan_and_admit(
                        session,
                        investigation_id,
                        investigation,
                        planner_provider,
                        planner_model,
                        budget_available,
                    )
                except PlannerError as exc:
                    stopped_reason = f"planner_output_rejected: {exc}"
                    break
                except Exception as exc:
                    stopped_reason = f"planner_failed: {type(exc).__name__}"
                    break
                continue
            stopped_reason = reason
            break
        lead_id = next(lid for lid, lead in pairs if lead is selected)
        attempted.add(str(lead_id))
        evaluation = evaluate_trigger(
            investigation,
            Lead(**selected.model_dump(exclude={"status"})),
            expansion_state=(
                ExpansionState.TARGET if selected.relation_depth == 0 else ExpansionState.RESEARCHED
            ),
            verified_relation=False,
            budget_available=budget_available,
        )
        if evaluation.decision in (
            TriggerDecision.CONTEXT_ONLY,
            TriggerDecision.BLOCKED_BY_SCOPE,
        ):
            await repository.set_lead_status(
                session, investigation_id, lead_id, "BLOCKED", evaluation.reason
            )
            blocked += 1
        elif evaluation.decision in (
            TriggerDecision.FOLLOW_UP_LEAD,
            TriggerDecision.VERIFICATION_LEAD,
        ):
            outcome = await execute_lead(session, investigation_id, lead_id, tools)
            if outcome == "COMPLETED":
                executed += 1
            elif outcome == "BLOCKED":
                blocked += 1
            else:
                failed += 1
        else:
            stopped_reason = evaluation.reason
            break
        await session.commit()
    else:
        stopped_reason = stopped_reason or "lead_cap_reached"

    summary = {
        "executed": executed,
        "blocked": blocked,
        "failed": failed,
        "planned": planned,
        "stopped_reason": stopped_reason,
    }
    await repository._audit(
        session,
        investigation_id,
        "RESEARCH_PASS_COMPLETED",
        {"job_id": str(job_id), "summary": summary},
    )
    await session.commit()
    return summary


async def run_research_pass(
    session: AsyncSession,
    investigation_id: UUID,
    tools: ExecutorTools | None = None,
    *,
    max_leads: int = 10,
    budget_available: bool = True,
    job_id: UUID | None = None,
    planner_provider: ChatProvider | None = None,
    planner_model: str | None = None,
) -> dict:
    """Persist real pass lifecycle separately from module coverage/completion."""
    job_id = job_id or uuid4()
    resolved_tools = tools if tools is not None else ExecutorTools()
    await repository.get_investigation_record(session, investigation_id)
    await repository.mark_investigation_active(session, investigation_id)
    await repository._audit(
        session, investigation_id, "RESEARCH_PASS_STARTED", {"job_id": str(job_id)}
    )
    await session.commit()
    logger = structlog.get_logger()
    logger.info("research_pass_started", job_id=str(job_id))
    try:
        return await _run_research_pass(
            session,
            investigation_id,
            resolved_tools,
            max_leads=max_leads,
            budget_available=budget_available,
            job_id=job_id,
            planner_provider=planner_provider,
            planner_model=planner_model,
        )
    except Exception as exc:
        await session.rollback()
        try:
            await repository._audit(
                session,
                investigation_id,
                "RESEARCH_PASS_FAILED",
                {"job_id": str(job_id), "error_code": "research_pass_failed"},
            )
            await session.commit()
        except Exception as audit_error:
            await session.rollback()
            logger.error(
                "research_pass_failure_audit_unavailable",
                job_id=str(job_id),
                error_type=type(audit_error).__name__,
            )
        logger.error("research_pass_failed", job_id=str(job_id), error_type=type(exc).__name__)
        raise
