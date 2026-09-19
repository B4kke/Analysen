"""Reduce append-only research audit events to a typed pass state."""

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.api.app.domain.models import (
    ResearchPassState,
    ResearchPassStatus,
    ResearchPassSummary,
)

_PHASES = {
    "RESEARCH_PASS_REQUESTED": (ResearchPassStatus.REQUESTED, 0, "requested_at"),
    "RESEARCH_PASS_ENQUEUED": (ResearchPassStatus.ENQUEUED, 1, "enqueued_at"),
    "RESEARCH_PASS_STARTED": (ResearchPassStatus.RUNNING, 2, "started_at"),
    "RESEARCH_PASS_FAILED": (ResearchPassStatus.FAILED, 3, "completed_at"),
    "RESEARCH_PASS_COMPLETED": (ResearchPassStatus.COMPLETED, 4, "completed_at"),
}


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def _summary(payload: Mapping[str, Any]) -> ResearchPassSummary | None:
    value = payload.get("summary")
    if not isinstance(value, Mapping):
        return None
    try:
        return ResearchPassSummary.model_validate(value)
    except ValueError:
        return None


def _event_time(row: Mapping[str, Any]) -> datetime | None:
    value = row.get("created_at")
    return value if isinstance(value, datetime) else None


def reduce_research_events(
    rows: Sequence[Mapping[str, Any]], *, has_activity: bool = False
) -> ResearchPassState:
    """Reduce events deterministically, including fast-worker reorderings.

    A job is selected by its first audit id, with the newest job winning. Its
    phase is selected by semantic phase rank, never by audit insertion order;
    this handles STARTED/COMPLETED committing before a late ENQUEUED event.
    """
    jobs: dict[UUID, list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    legacy: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if row.get("event_type") not in _PHASES:
            continue
        payload = _payload(row.get("payload"))
        try:
            job_id = UUID(str(payload.get("job_id", "")))
        except ValueError:
            legacy.append(row)
        else:
            jobs[job_id].append((int(row.get("id", index)), row))

    if jobs:
        selected_job, events = max(jobs.items(), key=lambda item: min(i for i, _ in item[1]))
        _, selected = max(
            events, key=lambda item: (_PHASES[str(item[1]["event_type"])][1], item[0])
        )
        status = _PHASES[str(selected["event_type"])][0]
        state = ResearchPassState(status=status, job_id=selected_job)
        for _, row in sorted(events, key=lambda item: item[0]):
            event = str(row["event_type"])
            _, _, field = _PHASES[event]
            # The selected terminal owns completed_at. Earlier phase events
            # may only fill their own first observed timestamps.
            if field != "completed_at" and getattr(state, field) is None:
                setattr(state, field, _event_time(row))
        if status in {ResearchPassStatus.COMPLETED, ResearchPassStatus.FAILED}:
            state.completed_at = _event_time(selected)
            payload = _payload(selected.get("payload"))
            if status == ResearchPassStatus.COMPLETED:
                state.summary = _summary(payload)
            else:
                code = payload.get("error_code")
                state.error_code = code if isinstance(code, str) else "research_pass_failed"
        return state

    if legacy:
        selected = max(legacy, key=lambda row: int(row.get("id", 0)))
        state = ResearchPassState(
            status=_PHASES[str(selected["event_type"])][0], legacy_activity=True
        )
        _, _, field = _PHASES[str(selected["event_type"])]
        setattr(state, field, _event_time(selected))
        payload = _payload(selected.get("payload"))
        if state.status == ResearchPassStatus.COMPLETED:
            state.summary = _summary(payload)
        elif state.status == ResearchPassStatus.FAILED:
            code = payload.get("error_code")
            state.error_code = code if isinstance(code, str) else "research_pass_failed"
        return state
    return ResearchPassState(
        status=(
            ResearchPassStatus.ACTIVITY_RECORDED if has_activity else ResearchPassStatus.NOT_STARTED
        )
    )
