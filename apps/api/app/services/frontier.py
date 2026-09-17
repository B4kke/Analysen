"""Deterministic frontier selection (AQ-012).

Orders executable leads by expected information value within scope and budget.
Only PENDING leads within the depth limit are eligible; anything else is left
for the evaluator or the scope gate. Selection is advisory — execution still
passes the lead gate at the tool boundary.
"""

from apps.api.app.domain.trigger_eval import FrontierLead


def select_next(
    leads: list[FrontierLead],
    *,
    max_depth: int,
    budget_available: bool = True,
) -> tuple[FrontierLead | None, str]:
    """Return the next executable lead and the selection reason.

    Reasons: "highest_priority" when a lead is selected, "budget_exhausted"
    when the budget stops everything, "no_executable_leads" when nothing is
    PENDING within the depth limit.
    """
    if not budget_available:
        return None, "budget_exhausted"
    eligible = [
        lead
        for lead in leads
        if lead.status == "PENDING" and lead.depth <= max_depth
    ]
    if not eligible:
        return None, "no_executable_leads"
    eligible.sort(key=lambda lead: (-lead.priority, lead.depth))
    return eligible[0], "highest_priority"
