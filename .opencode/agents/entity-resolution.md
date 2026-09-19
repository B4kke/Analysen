---
description: Implements conservative entity resolution for Norwegian persons and organizations using deterministic candidate generation, negative signals and human-review states.
mode: subagent
---

Load analysen-entity-resolution and analysen-provenance.

Implement identity resolution conservatively:
- same name alone never merges people,
- exact conflicting birth dates are hard negatives,
- impossible role/location/timeline combinations lower or block matching,
- MATCH / PROBABLE_MATCH / UNRESOLVED / NOT_MATCH have deterministic semantics,
- PROBABLE_MATCH requires human review before merge,
- related entities default to CONTEXT_ONLY unless scope independently authorizes research,
- merge/split actions are audited.

Build a gold fixture set with Norwegian letters, name variants, namesakes, historical roles and explicit conflicts. Optimize for very low false-positive merge rate, not maximum auto-merge.
