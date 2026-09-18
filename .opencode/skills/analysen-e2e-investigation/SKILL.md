---
name: Analysen end-to-end investigation
description: Prove Analysen works through a real vertical investigation path across web/API/worker/database using controlled source fixtures and real persistence rather than disconnected mocks.
---

# Minimum vertical proof

Create a fresh investigation and verify:
1. request shape and scope are persisted,
2. research start queues or invokes a pass,
3. planner creates a schema-valid proposal when needed,
4. lead gate persists PENDING/BLOCKED correctly,
5. frontier and trigger evaluator choose a legal action,
6. source router selects an allowlisted executor,
7. controlled source fixture is fetched,
8. raw content is stored and hash-verified,
9. Document/Evidence/Claim records persist,
10. verifier produces a valid state where applicable,
11. coverage/status update,
12. UI/report API reflects the stored result,
13. rerun does not duplicate immutable/terminal work.

Mocks are allowed only at the external network/model boundary. Do not mock repositories, database transitions or the orchestration layers the test claims to verify.
