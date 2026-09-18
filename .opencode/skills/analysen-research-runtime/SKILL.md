---
name: Analysen research runtime
description: Build and verify SearXNG discovery, safe web fetching, research dependencies, crawl limits, redirect SSRF protection, robots handling and web raw provenance.
---

# Runtime checklist

- The API/worker image used for research installs the required research dependencies.
- Browser binaries needed by Playwright are installed in the runtime that invokes it.
- Discovery and fetch are separate stages.
- Validate initial URL and every redirect/final destination against public-network policy.
- Enforce content-size limits while streaming where possible.
- Enforce per-domain delay/concurrency/page budget.
- Respect explicit robots/access restrictions where applicable; never bypass login/CAPTCHA/paywalls.
- Keep failures typed and visible in coverage/stop reasons.
- Persist raw fetched content before extraction.
- Canonical URL is metadata/dedup key, not a substitute for raw content.

# Test strategy

Network clients must be injectable. Unit tests use controlled fake transports; integration tests may use a local fixture server to exercise redirects, content limits and blocked private-address redirects without arbitrary internet calls.
