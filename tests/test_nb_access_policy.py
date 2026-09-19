"""Fail-closed access policy matrix tests (AQ-031).

Tests that every access state is decided correctly and unknown/incomplete
metadata never upgrades to reuse or embed rights.
"""

import pytest

from apps.api.app.services.nb_access_policy import (
    NBAccessDecision,
    NBAccessState,
    decide_access,
    ensure_page_fetch_permitted,
    ensure_report_embed_permitted,
)


class TestAccessPolicyMatrix:
    """Matrix tests for all five access states."""

    def test_unknown_incomplete_metadata_fails_closed(self):
        """Unknown or empty metadata -> UNKNOWN state, minimal permissions."""
        decision = decide_access({})
        assert decision.state == NBAccessState.UNKNOWN
        assert decision.allow_metadata is True
        assert decision.allow_context is False
        assert decision.allow_full_text_storage is False
        assert decision.allow_page_fetch is False
        assert decision.allow_derived_crop is False
        assert decision.allow_report_embed is False
        assert "fail closed" in decision.reason.lower()

    def test_only_viewability_all_no_reuse_proof(self):
        """viewability=ALL alone grants PUBLIC_VIEW_ONLY, not embed."""
        decision = decide_access({"viewability": "ALL"})
        assert decision.state == NBAccessState.PUBLIC_VIEW_ONLY
        assert decision.allow_metadata is True
        assert decision.allow_context is True
        assert decision.allow_full_text_storage is False
        assert decision.allow_page_fetch is True
        assert decision.allow_derived_crop is True
        assert decision.allow_report_embed is False
        assert "viewability alone grants no embed rights" in decision.reason.lower()

    def test_public_domain_true_no_restriction(self):
        """isPublicDomain=true without library restriction -> PUBLIC_REUSE."""
        decision = decide_access(
            {"isPublicDomain": True, "accessAllowedFrom": "EVERYWHERE"}
        )
        assert decision.state == NBAccessState.PUBLIC_REUSE
        assert decision.allow_metadata is True
        assert decision.allow_context is True
        assert decision.allow_full_text_storage is True
        assert decision.allow_page_fetch is True
        assert decision.allow_derived_crop is True
        assert decision.allow_report_embed is True

    def test_public_domain_true_with_library_restriction(self):
        """isPublicDomain=true but accessAllowedFrom=LIBRARY -> LIBRARY_ONLY."""
        decision = decide_access(
            {"isPublicDomain": True, "accessAllowedFrom": "LIBRARY"}
        )
        assert decision.state == NBAccessState.LIBRARY_ONLY
        assert decision.allow_report_embed is False

    def test_open_license_everywhere_access(self):
        """Open license (CC0/PD) with everywhere access -> PUBLIC_REUSE.

        Note: isPublicDomain must not be explicitly false, otherwise
        public_domain_false blocks the open license upgrade.
        """
        decision = decide_access(
            {
                "license": "CC0",
                "accessAllowedFrom": "EVERYWHERE",
                # isPublicDomain not set (not explicitly false)
            }
        )
        assert decision.state == NBAccessState.PUBLIC_REUSE
        assert decision.allow_report_embed is True

    def test_open_license_not_everywhere(self):
        """Open license but not everywhere access -> does not upgrade to reuse."""
        decision = decide_access(
            {"license": "CC0", "accessAllowedFrom": "LIBRARY"}
        )
        # Should be LIBRARY_ONLY because access is restricted
        assert decision.state == NBAccessState.LIBRARY_ONLY

    def test_library_only_access(self):
        """accessAllowedFrom=LIBRARY -> LIBRARY_ONLY."""
        decision = decide_access({"accessAllowedFrom": "LIBRARY"})
        assert decision.state == NBAccessState.LIBRARY_ONLY
        assert decision.allow_page_fetch is False
        assert decision.allow_report_embed is False

    def test_nb_only_access(self):
        """accessAllowedFrom=NB_ONLY/lesesal -> NB_ONLY."""
        for token in ["NB_ONLY", "nb", "lesesal", "readingroom"]:
            decision = decide_access({"accessAllowedFrom": token})
            assert decision.state == NBAccessState.NB_ONLY, f"Failed for {token}"
            assert decision.allow_page_fetch is False
            assert decision.allow_report_embed is False

    def test_public_view_only_variants(self):
        """Various everywhere tokens -> PUBLIC_VIEW_ONLY (not reuse)."""
        for token in ["EVERYWHERE", "ALL", "PUBLIC", "OPEN", "EVERYONE"]:
            decision = decide_access({"accessAllowedFrom": token})
            assert decision.state == NBAccessState.PUBLIC_VIEW_ONLY, f"Failed for {token}"
            assert decision.allow_report_embed is False, f"Embed allowed for {token}"

    def test_unrecognized_combination_fails_closed(self):
        """Unrecognized rights combination -> UNKNOWN, fail closed."""
        decision = decide_access(
            {"accessAllowedFrom": "MYSTERY_TOKEN", "viewability": "PARTIAL"}
        )
        assert decision.state == NBAccessState.UNKNOWN
        assert decision.allow_context is False
        assert decision.allow_page_fetch is False
        assert decision.allow_report_embed is False

    def test_upstream_fields_preserved(self):
        """Upstream access fields are preserved in decision.upstream."""
        metadata = {
            "accessAllowedFrom": "EVERYWHERE",
            "viewability": "ALL",
            "isPublicDomain": False,
            "license": "NLOD-2.0",
            "rightsUri": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Nasjonalbiblioteket",
        }
        decision = decide_access(metadata)
        assert decision.upstream["accessAllowedFrom"] == "EVERYWHERE"
        assert decision.upstream["viewability"] == "ALL"
        assert decision.upstream["isPublicDomain"] is False
        assert decision.upstream["license"] == "NLOD-2.0"
        assert decision.upstream["rightsUri"] == "https://creativecommons.org/licenses/by/4.0/"
        assert decision.upstream["attribution"] == "Nasjonalbiblioteket"

    def test_case_insensitive_keys(self):
        """Lookup is case-insensitive for upstream keys."""
        decision = decide_access(
            {
                "ACCESSALLOWEDFROM": "EVERYWHERE",
                "VIEWABILITY": "ALL",
                "ISPUBLICDOMAIN": "false",
                "LICENSECODE": "NLOD-2.0",
            }
        )
        assert decision.state == NBAccessState.PUBLIC_VIEW_ONLY


class TestAccessGates:
    """Tests for the rights gate helpers."""

    def test_ensure_page_fetch_permitted_allows_public_reuse(self):
        decision = NBAccessDecision(
            state=NBAccessState.PUBLIC_REUSE,
            upstream={},
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=True,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=True,
            reason="test",
        )
        ensure_page_fetch_permitted(decision)  # Should not raise

    def test_ensure_page_fetch_permitted_allows_public_view_only(self):
        decision = NBAccessDecision(
            state=NBAccessState.PUBLIC_VIEW_ONLY,
            upstream={},
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=False,
            reason="test",
        )
        ensure_page_fetch_permitted(decision)  # Should not raise

    def test_ensure_page_fetch_permitted_denies_library_only(self):
        decision = NBAccessDecision(
            state=NBAccessState.LIBRARY_ONLY,
            upstream={},
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=False,
            allow_derived_crop=False,
            allow_report_embed=False,
            reason="test",
        )
        with pytest.raises(Exception) as exc_info:
            ensure_page_fetch_permitted(decision)
        assert "page fetch denied" in str(exc_info.value).lower()
        assert exc_info.value.state == NBAccessState.LIBRARY_ONLY

    def test_ensure_page_fetch_permitted_denies_nb_only(self):
        decision = NBAccessDecision(
            state=NBAccessState.NB_ONLY,
            upstream={},
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=False,
            allow_derived_crop=False,
            allow_report_embed=False,
            reason="test",
        )
        with pytest.raises(Exception) as exc_info:
            ensure_page_fetch_permitted(decision)
        assert exc_info.value.state == NBAccessState.NB_ONLY

    def test_ensure_page_fetch_permitted_denies_unknown(self):
        decision = NBAccessDecision(
            state=NBAccessState.UNKNOWN,
            upstream={},
            allow_metadata=True,
            allow_context=False,
            allow_full_text_storage=False,
            allow_page_fetch=False,
            allow_derived_crop=False,
            allow_report_embed=False,
            reason="test",
        )
        with pytest.raises(Exception) as exc_info:
            ensure_page_fetch_permitted(decision)
        assert exc_info.value.state == NBAccessState.UNKNOWN

    def test_ensure_report_embed_permitted_denies_public_view_only(self):
        """PUBLIC_VIEW_ONLY must NOT allow report embed (viewability alone)."""
        decision = NBAccessDecision(
            state=NBAccessState.PUBLIC_VIEW_ONLY,
            upstream={},
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=False,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=False,
            reason="viewability alone grants no embed rights",
        )
        with pytest.raises(Exception) as exc_info:
            ensure_report_embed_permitted(decision)
        assert "report embed denied" in str(exc_info.value).lower()

    def test_ensure_report_embed_permitted_allows_public_reuse(self):
        decision = NBAccessDecision(
            state=NBAccessState.PUBLIC_REUSE,
            upstream={},
            allow_metadata=True,
            allow_context=True,
            allow_full_text_storage=True,
            allow_page_fetch=True,
            allow_derived_crop=True,
            allow_report_embed=True,
            reason="test",
        )
        ensure_report_embed_permitted(decision)  # Should not raise

    def test_all_states_enum_covered(self):
        """Ensure we test all NBAccessState enum values."""
        tested = {
            NBAccessState.UNKNOWN,
            NBAccessState.PUBLIC_REUSE,
            NBAccessState.PUBLIC_VIEW_ONLY,
            NBAccessState.LIBRARY_ONLY,
            NBAccessState.NB_ONLY,
        }
        assert tested == set(NBAccessState)