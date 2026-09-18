---
name: Analysen entity resolution
description: Implement conservative Norwegian person and organization resolution using candidate generation, deterministic signals, hard negatives and auditable human review.
---

# Priority

Minimize false-positive merges. It is acceptable to remain UNRESOLVED.

# Required signals

Strong positives:
- exact authoritative identifier,
- exact birth date with compatible role history,
- authoritative source reference.

Hard/strong negatives:
- different exact birth dates,
- impossible overlapping identity/timeline,
- explicit authoritative mismatch.

Weak signals such as name, municipality, title or social similarity never auto-merge by themselves.

# States

- MATCH: strong evidence, no hard contradiction.
- PROBABLE_MATCH: persuasive but requires human approval before merge.
- UNRESOLVED: ambiguous or insufficient.
- NOT_MATCH: hard conflict.

Every merge/split and resolution decision must be auditable and evidence-linked.
