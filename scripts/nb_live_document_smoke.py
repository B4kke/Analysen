"""Bounded NB live document contract probe; public institutional topic only.

No full pages, historical text or personal records are written to disk.
Only counts, typed outcomes and non-content diagnostics leave the process.
An image or crop is tested only when both search and fresh item metadata
explicitly permit reuse. Skipped image rights are not extraction success.
"""
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from apps.api.app.services.nb_access_policy import decide_access
from apps.api.app.services.nb_article_extract import (
    NBExtractError,
    extract_permitted_article,
    page_image_size,
)
from apps.api.app.services.nb_article_locator import (
    match_page_anchors,
    parse_content_fragments,
    parse_iiif_anchors,
)
from apps.api.app.sources.national_library import (
    NationalLibraryClient,
    NBClientError,
    NBMediaClientAdapter,
    parse_catalog_search_payload,
)

QUERY = "Stortinget"
MAX_ISSUES = 2
MAX_PAGES = 2


def failure(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, NBClientError):
        return {"status": "failed", "code": exc.code, "http_status": exc.status_code}
    if isinstance(exc, NBExtractError):
        return {"status": "failed", "code": exc.code}
    return {"status": "failed", "code": type(exc).__name__}


async def run() -> dict[str, Any]:
    client = NationalLibraryClient()
    adapter = NBMediaClientAdapter(client)
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "catalog": {"status": "not_run"},
        "issues": [],
    }
    image_attempted = False
    try:
        async with asyncio.timeout(25):
            total, candidates, _ = await client.search_newspapers(
                QUERY, limit=MAX_ISSUES
            )
        report["catalog"] = {
            "status": "passed" if candidates else "no_candidates",
            "total": total,
            "returned": len(candidates),
        }
        for index, candidate in enumerate(candidates, start=1):
            decision = decide_access(candidate.access_metadata)
            item: dict[str, Any] = {
                "rank": index,
                "access": decision.state.value,
                "locators": {"status": "not_run"},
                "anchors": {"status": "not_run"},
                "correlation": {"status": "not_run"},
                "image": {"status": "not_run"},
                "crop": {"status": "not_run"},
            }
            report["issues"].append(item)
            await asyncio.sleep(1)
            pages = []
            anchors = []
            try:
                async with asyncio.timeout(25):
                    raw = await client.content_fragments(
                        candidate.item_id, QUERY, max_pages=MAX_PAGES
                    )
                pages = parse_content_fragments(
                    raw.payload, item_id=candidate.item_id, query=QUERY, max_pages=MAX_PAGES
                )
                item["locators"] = {"status": "passed", "count": len(pages)}
            except Exception as exc:
                item["locators"] = failure(exc)
            await asyncio.sleep(1)
            try:
                async with asyncio.timeout(25):
                    raw = await client.iiif_search(candidate.item_id, QUERY)
                anchors = parse_iiif_anchors(raw.payload, query=QUERY)
                item["anchors"] = {"status": "passed", "count": len(anchors)}
            except Exception as exc:
                item["anchors"] = failure(exc)

            correlated = []
            pairs = [(anchor.page_urn, anchor.xywh) for anchor in anchors]
            for page in pages:
                matches = match_page_anchors(
                    pairs,
                    item_id=candidate.item_id,
                    issue_urn=candidate.issue_urn,
                    page_urn=page.page_urn,
                    page_number=page.page_number,
                )
                if matches:
                    correlated.append((page, matches))
            item["correlation"] = {
                "status": "passed" if correlated else "no_correlated_page",
                "matched_pages": len(correlated),
            }
            if not (decision.allow_page_fetch and decision.allow_report_embed):
                item["image"] = {"status": "skipped_rights"}
                continue
            if not correlated or image_attempted:
                item["image"] = {"status": "skipped_no_anchor_or_budget"}
                continue
            # Fresh detail must independently justify permission and match
            # the item identity; a catalog teaser cannot grant reuse alone.
            await asyncio.sleep(1)
            try:
                async with asyncio.timeout(25):
                    record = await client.get_item(candidate.item_id)
                _, fresh = parse_catalog_search_payload(
                    {"items": [record.payload]}, query=QUERY, limit=1
                )
                if not fresh or fresh[0].item_id != candidate.item_id:
                    item["image"] = {"status": "skipped_unverified_item"}
                    continue
                fresh_decision = decide_access(fresh[0].access_metadata)
                if not (
                    fresh_decision.allow_page_fetch and fresh_decision.allow_report_embed
                ):
                    item["image"] = {"status": "skipped_rights"}
                    continue
                page, matches = correlated[0]
                image_attempted = True
                async with asyncio.timeout(35):
                    original = await adapter.fetch_page_image(page.page_urn)
                width, height = page_image_size(original)
                item["image"] = {
                    "status": "passed",
                    "width": width,
                    "height": height,
                    "bytes": len(original),
                }
                try:
                    result = await asyncio.to_thread(
                        extract_permitted_article,
                        original,
                        page_urn=page.page_urn,
                        anchor_xywh=matches,
                        target_expression=QUERY,
                    )
                    item["crop"] = {
                        "status": "passed" if result.target_validated else "unvalidated",
                        "pixels": result.region.w * result.region.h,
                        "ocr_words": result.ocr_word_count,
                        "ocr_mean_confidence": result.ocr_mean_confidence,
                    }
                except Exception as exc:
                    item["crop"] = failure(exc)
            except Exception as exc:
                item["image"] = failure(exc)
    except Exception as exc:
        report["catalog"] = failure(exc)
    finally:
        await adapter.aclose()
    report["locator_contract_verified"] = (
        report["catalog"]["status"] == "passed"
        and any(issue["correlation"]["status"] == "passed" for issue in report["issues"])
    )
    report["live_image_verified"] = any(
        issue["image"]["status"] == "passed" for issue in report["issues"]
    )
    report["live_crop_verified"] = any(
        issue["crop"]["status"] == "passed" for issue in report["issues"]
    )
    return report


def main() -> int:
    report = asyncio.run(run())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    failed_endpoint = any(
        issue[step]["status"] == "failed"
        for issue in report["issues"]
        for step in ("locators", "anchors", "image", "crop")
    )
    return int(not report["locator_contract_verified"] or failed_endpoint)


if __name__ == "__main__":
    raise SystemExit(main())
