"""Bounded research pass: frontier selection, trigger evaluation, execution.

One pass processes admitted PENDING leads until the frontier is empty, the
budget is spent, or the lead cap is reached. Each lead is committed separately
so a crash resumes without double-fetch (re-execution is a no-op for terminal
leads). Leads the evaluator routes to CONTEXT_ONLY or BLOCKED_BY_SCOPE are
marked BLOCKED with the reason so the pass terminates; they can be
re-proposed later if scope changes. No model calls.
"""

from uuid import UUID, uuid4

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.domain.models import Lead
from apps.api.app.domain.scope import ExpansionState
from apps.api.app.domain.trigger_eval import FrontierLead, TriggerDecision
from apps.api.app.repositories import investigations as repository
from apps.api.app.services.frontier import select_next
from apps.api.app.services.lead_executor import FetchFn, execute_lead
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


async def _run_research_pass(
    session: AsyncSession,
    investigation_id: UUID,
    fetch: FetchFn,
    *,
    max_leads: int = 10,
    budget_available: bool = True,
    job_id: UUID,
) -> dict:
    """Run one bounded pass; return an audited summary dict."""
    investigation = await repository.get_investigation_record(session, investigation_id)
    executed = 0
    blocked = 0
    failed = 0
    stopped_reason = ""
    attempted: set[str] = set()

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
            outcome = await execute_lead(session, investigation_id, lead_id, fetch)
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
    fetch: FetchFn,
    *,
    max_leads: int = 10,
    budget_available: bool = True,
    job_id: UUID | None = None,
) -> dict:
    """Persist real pass lifecycle separately from module coverage/completion."""
    job_id = job_id or uuid4()
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
            fetch,
            max_leads=max_leads,
            budget_available=budget_available,
            job_id=job_id,
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
