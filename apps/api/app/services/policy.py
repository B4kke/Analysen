from dataclasses import dataclass

BLOCKED_SENSITIVE_INFERENCES = frozenset(
    {
        "ethnicity",
        "race",
        "religion",
        "health",
        "sexual_orientation",
        "sex_life",
        "political_opinion",
    }
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


def check_inference_category(category: str) -> PolicyDecision:
    normalized = category.strip().casefold()
    if normalized in BLOCKED_SENSITIVE_INFERENCES:
        return PolicyDecision(False, f"blocked_sensitive_inference:{normalized}")
    return PolicyDecision(True, "allowed")
