"""Media Mentions repository (AQ-031, Nasjonalbiblioteket media).

Persists media_mentions rows against the canonical shape that
0006_nb_media migration guarantees (idempotency semantics fixed by
0008_media_mentions_nulls_not_distinct). The repository accepts plain Python
values matching the table columns and uses ON CONFLICT on the
idempotency key (investigation_id, page_urn, target_query).

The idempotency key is UNIQUE NULLS NOT DISTINCT, so page_urn=None rows
are deduplicated exactly like located rows: repeated upserts for the same
(investigation_id, target_query) refresh a single row.
"""

import json
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_media_mention(
    session: AsyncSession,
    *,
    investigation_id: UUID,
    target_query: str,
    publication: str | None = None,
    published_at: date | None = None,
    page_number: int | None = None,
    issue_urn: str | None = None,
    page_urn: str | None = None,
    headline: str | None = None,
    summary: str | None = None,
    text_excerpt: str | None = None,
    text_availability: str = "UNAVAILABLE",
    identity_state: str = "UNRESOLVED",
    source_url: str | None = None,
    access_class: str | None = None,
    license_code: str | None = None,
    image_document_id: UUID | None = None,
    image_embeddable: bool = False,
    evidence_id: UUID | None = None,
    xywh_anchors: list[str] | None = None,
) -> UUID:
    """Insert or refresh a media mention by idempotency key.

    Deduplicates on (investigation_id, page_urn, target_query), including
    page_urn=None rows: the key is UNIQUE NULLS NOT DISTINCT (migration
    0008), so the ON CONFLICT arbiter matches NULL page_urn exactly like a
    real page URN. ``evidence_id`` links the mention to its stored crop
    evidence (migration 0009); mentions without stored evidence keep NULL.
    ``xywh_anchors`` stores the correlated IIIF text anchors for the page
    (migration 0010); rows without anchors keep NULL.
    Returns the row id (existing or newly inserted).
    """
    # Validate text_availability
    if text_availability not in ("FULL", "PARTIAL_CONTEXT", "UNAVAILABLE"):
        raise ValueError(f"invalid text_availability: {text_availability}")
    # Anchors are stored verbatim but never as empty strings: an empty list
    # means "no anchors", exactly like NULL on read.
    cleaned_anchors: list[str] | None = None
    if xywh_anchors is not None:
        cleaned_anchors = [a for a in xywh_anchors if isinstance(a, str) and a.strip()]
        if not cleaned_anchors:
            cleaned_anchors = None

    row = (
        await session.execute(
            text("""
                INSERT INTO media_mentions (
                    investigation_id, target_query, publication, published_at,
                    page_number, issue_urn, page_urn, headline, summary,
                    text_excerpt, text_availability, identity_state, source_url,
                    access_class, license_code, image_document_id, image_embeddable,
                    evidence_id, xywh_anchors
                ) VALUES (
                    :investigation_id, :target_query, :publication, :published_at,
                    :page_number, :issue_urn, :page_urn, :headline, :summary,
                    :text_excerpt, :text_availability, :identity_state, :source_url,
                    :access_class, :license_code, :image_document_id, :image_embeddable,
                    :evidence_id, CAST(:xywh_anchors AS jsonb)
                )
                ON CONFLICT (investigation_id, page_urn, target_query) DO UPDATE SET
                    publication = EXCLUDED.publication,
                    published_at = EXCLUDED.published_at,
                    page_number = EXCLUDED.page_number,
                    issue_urn = EXCLUDED.issue_urn,
                    headline = EXCLUDED.headline,
                    summary = EXCLUDED.summary,
                    text_excerpt = EXCLUDED.text_excerpt,
                    text_availability = EXCLUDED.text_availability,
                    identity_state = EXCLUDED.identity_state,
                    source_url = EXCLUDED.source_url,
                    access_class = EXCLUDED.access_class,
                    license_code = EXCLUDED.license_code,
                    image_document_id = EXCLUDED.image_document_id,
                    image_embeddable = EXCLUDED.image_embeddable,
                    evidence_id = EXCLUDED.evidence_id,
                    xywh_anchors = EXCLUDED.xywh_anchors
                RETURNING id
            """),
            {
                "investigation_id": investigation_id,
                "target_query": target_query,
                "publication": publication,
                "published_at": published_at,
                "page_number": page_number,
                "issue_urn": issue_urn,
                "page_urn": page_urn,
                "headline": headline,
                "summary": summary,
                "text_excerpt": text_excerpt,
                "text_availability": text_availability,
                "identity_state": identity_state,
                "source_url": source_url,
                "access_class": access_class,
                "license_code": license_code,
                "image_document_id": image_document_id,
                "image_embeddable": image_embeddable,
                "evidence_id": evidence_id,
                "xywh_anchors": json.dumps(cleaned_anchors) if cleaned_anchors else None,
            },
        )
    ).mappings().one()
    return row["id"]


async def list_media_mentions(
    session: AsyncSession,
    investigation_id: UUID,
) -> list[dict[str, Any]]:
    """List all media mentions for an investigation, ordered by published_at then page_number."""
    rows = (
        await session.execute(
            text("""
                SELECT *
                FROM media_mentions
                WHERE investigation_id = :iid
                ORDER BY published_at NULLS LAST, page_number NULLS LAST
            """),
            {"iid": investigation_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]

async def update_media_mention_identity(
    session: AsyncSession,
    mention_id: UUID,
    *,
    identity_state: str,
) -> None:
    """Persist the deterministic identity decision for one media mention."""
    if identity_state not in ("MATCH", "PROBABLE_MATCH", "UNRESOLVED", "NOT_MATCH"):
        raise ValueError(f"invalid identity_state: {identity_state}")
    result = await session.execute(
        text("""
            UPDATE media_mentions
            SET identity_state = :identity_state
            WHERE id = :mention_id
            RETURNING id
        """),
        {"mention_id": mention_id, "identity_state": identity_state},
    )
    if result.mappings().one_or_none() is None:
        raise LookupError(f"unknown media mention: {mention_id}")
