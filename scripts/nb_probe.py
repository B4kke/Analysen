#!/usr/bin/env python3
"""Optional live contract probe for Nasjonalbiblioteket endpoints (AQ-031).

Usage:
    python scripts/nb_probe.py --query "Maylen Sorkness Andersen" --limit 5
    python scripts/nb_probe.py --query "Eltonåsen" --limit 3

This script:
- Uses REAL network calls to NB endpoints (requires internet)
- Does NOT write fixtures or persist full text
- Shows: query, total candidates, publication/date, item ID, page/page URN,
  rights/access state, contentfragments behavior, IIIF xywh, DH-lab status
- With --probe-images: attempts the IIIF image resolver for located pages
  (typed outcome, bytes never persisted)
- Fails gracefully without network/key

Diagnostics only - not for CI assertions (live counts are mutable).
"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

# Repo root on sys.path so the documented `python scripts/nb_probe.py` runs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.app.services.nb_access_policy import decide_access
from apps.api.app.services.nb_article_locator import (
    parse_content_fragments,
    parse_dh_concordance,
    parse_iiif_anchors,
)
from apps.api.app.sources.national_library import (
    NationalLibraryClient,
    NBClientError,
    NBMediaClientAdapter,
)


async def probe_image(adapter: NBMediaClientAdapter, page_urns: list[str]) -> None:
    """Diagnostics: attempt the IIIF resolver for located pages.

    The outcome is typed (bytes length or NBClientError code) and printed for
    endpoint-shape verification only. No bytes are persisted or committed.
    """
    print(f"\n   Image resolver probe ({len(page_urns[:2])} pages)")
    print("      " + "-" * 36)
    for urn in page_urns[:2]:
        try:
            image = await adapter.fetch_page_image(urn)
            print(f"      {urn}: OK, {len(image)} bytes")
        except NBClientError as e:
            status = f" status {e.status_code}" if e.status_code else ""
            print(f"      {urn}: {e.code}{status} - {e.message}")
        except Exception as e:  # probe-only: report and continue
            print(f"      {urn}: {type(e).__name__} - {e}")


async def run_probe(query: str, limit: int, *, probe_images: bool = False) -> None:
    print(f"\n{'='*70}")
    print(f"NB Live Probe: query='{query}', limit={limit}")
    print(f"{'='*70}\n")

    client = NationalLibraryClient()
    adapter = NBMediaClientAdapter(client)
    try:
        # 1. Catalog search
        print("1. Catalog FULL_TEXT_SEARCH")
        print("-" * 40)
        total, candidates, raw = await client.search_newspapers(query, limit=limit)
        print(f"   Total hits: {total}")
        print(f"   Returned: {len(candidates)} (capped at {limit})")
        print(f"   Raw response keys: {list(raw.payload.keys())}")

        if not candidates:
            print("   No candidates found.")
            return

        for i, cand in enumerate(candidates, 1):
            print(f"\n   [{i}] {cand.publication} — {cand.issued_at}")
            print(f"       item_id: {cand.item_id}")
            print(f"       issue_urn: {cand.issue_urn}")
            print(f"       rank: {cand.rank}")

            # Access decision
            decision = decide_access(cand.access_metadata)
            print(f"       access state: {decision.state.value}")
            print(f"       allow_page_fetch: {decision.allow_page_fetch}")
            print(f"       allow_report_embed: {decision.allow_report_embed}")
            print(f"       reason: {decision.reason}")

            # 2. contentfragments (page locator)
            print("\n   2. contentfragments (page locator)")
            print("      " + "-" * 36)
            try:
                cf_raw = await client.content_fragments(cand.item_id, query)
                locators = parse_content_fragments(
                    cf_raw.payload, item_id=cand.item_id, query=query
                )
                print(f"      Pages located: {len(locators)}")
                for loc in locators[:3]:
                    print(f"        - page {loc.page_number}: {loc.page_urn}")
                if len(locators) > 3:
                    print(f"        ... and {len(locators) - 3} more")
                # Show fragment text sample (first 200 chars)
                frag_entries = cf_raw.payload.get("fragments", [])
                if frag_entries:
                    sample = frag_entries[0].get("text", "")
                    print(f"      Fragment sample: {sample[:200]}")
                if probe_images and locators:
                    await probe_image(
                        adapter, [loc.page_urn for loc in locators if loc.page_urn]
                    )
            except NBClientError as e:
                print(f"      Error: {e.code} - {e.message}")

            # 3. IIIF Content Search (xywh)
            print("\n   3. IIIF Content Search (xywh anchors)")
            print("      " + "-" * 36)
            try:
                iiif_raw = await client.iiif_search(cand.item_id, query)
                anchors = parse_iiif_anchors(iiif_raw.payload, query=query)
                print(f"      Anchors found: {len(anchors)}")
                for anchor in anchors[:3]:
                    print(f"        - {anchor.page_urn} {anchor.xywh}")
                if len(anchors) > 3:
                    print(f"        ... and {len(anchors) - 3} more")
            except NBClientError as e:
                print(f"      Error: {e.code} - {e.message}")

            # 4. DH-lab concordance
            print("\n   4. DH-lab /conc (PARTIAL_CONTEXT)")
            print("      " + "-" * 36)
            try:
                # Get page URNs from locators for concordance
                cf_raw = await client.content_fragments(cand.item_id, query)
                locators = parse_content_fragments(
                    cf_raw.payload, item_id=cand.item_id, query=query
                )
                page_urns = [loc.page_urn for loc in locators if loc.page_urn]
                if page_urns:
                    conc_raw = await client.dh_concordance(page_urns[:5], query)
                    rows = parse_dh_concordance(conc_raw.payload)
                    print(f"      Concordance rows: {len(rows)}")
                    for row in rows[:2]:
                        print(f"        - {row.urn}: ...{row.before}[{row.match}]{row.after}...")
                    if len(rows) > 2:
                        print(f"        ... and {len(rows) - 2} more")
                else:
                    print("      No page URNs for concordance")
            except NBClientError as e:
                print(f"      Error: {e.code} - {e.message}")

            # Stop after first few candidates for readability
            if i >= 3 and limit > 3:
                remaining = len(candidates) - i
                print(f"\n   ... and {remaining} more candidates (use --limit to see more)")
                break

    except NBClientError as e:
        print(f"\nNB Client Error: {e.code} - {e.message}")
        if e.status_code:
            print(f"HTTP Status: {e.status_code}")
        sys.exit(1)
    except httpx.ConnectError:
        print("\nNetwork error: Could not connect to NB endpoints.")
        print("Check internet connection and NB API availability.")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        await client.aclose()

    print(f"\n{'='*70}")
    print("Probe complete.")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="NB live contract probe (diagnostics only, not for CI)"
    )
    parser.add_argument(
        "--query", default="Maylen Sorkness Andersen", help="Search query"
    )
    parser.add_argument(
        "--limit", type=int, default=5, help="Max candidates to process"
    )
    parser.add_argument(
        "--probe-images",
        action="store_true",
        help="Also attempt the IIIF image resolver for located pages (diagnostics)",
    )
    args = parser.parse_args()

    asyncio.run(run_probe(args.query, args.limit, probe_images=args.probe_images))


if __name__ == "__main__":
    main()