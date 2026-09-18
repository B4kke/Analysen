"""Unit tests for URL canonicalization pure functions (AQ-021).

Covers canonicalize_url and deduplicate_urls without network access.
"""

from apps.api.app.services.url_canonicalization import canonicalize_url, deduplicate_urls


def test_scheme_normalized_to_https() -> None:
    assert canonicalize_url("http://example.com/a") == "https://example.com/a"
    assert canonicalize_url("https://example.com/a") == "https://example.com/a"


def test_host_lowercased_and_www_removed() -> None:
    assert canonicalize_url("https://www.example.com/a") == "https://example.com/a"
    assert canonicalize_url("https://WWW.Example.COM/a") == "https://example.com/a"


def test_path_case_is_preserved_while_host_is_lowercased() -> None:
    assert canonicalize_url("https://WWW.EXAMPLE.COM/Page") == "https://example.com/Page"


def test_trailing_slash_removed_except_root() -> None:
    assert canonicalize_url("https://example.com/page/") == "https://example.com/page"
    assert canonicalize_url("https://example.com/") == "https://example.com/"
    assert canonicalize_url("https://example.com") == "https://example.com/"


def test_duplicate_slashes_collapsed() -> None:
    assert canonicalize_url("https://example.com//a///b//c/") == "https://example.com/a/b/c"
    assert canonicalize_url("https://example.com//a//") == "https://example.com/a"


def test_tracking_params_stripped_others_preserved_and_sorted() -> None:
    value = canonicalize_url("https://example.com/page?b=2&a=1&utm_medium=y&fbclid=abc&gclid=123")
    assert value == "https://example.com/page?a=1&b=2"


def test_tracking_param_matching_is_case_insensitive() -> None:
    assert canonicalize_url("https://example.com/page?UTM_SOURCE=x&b=2") == "https://example.com/page?b=2"


def test_only_tracking_params_leaves_no_query_string() -> None:
    assert canonicalize_url("https://example.com/page?utm_source=x") == "https://example.com/page"
    assert canonicalize_url("https://example.com/page?fbclid=abc&gclid=123") == "https://example.com/page"


def test_non_tracking_params_sorted() -> None:
    assert canonicalize_url("https://example.com/page?b=2&a=1") == "https://example.com/page?a=1&b=2"


def test_normal_fragment_preserved() -> None:
    assert canonicalize_url("https://example.com/page#section") == "https://example.com/page#section"


def test_bang_fragment_stripped() -> None:
    assert canonicalize_url("https://example.com/page#!tracking") == "https://example.com/page"


def test_empty_fragment_leaves_no_hash() -> None:
    assert canonicalize_url("https://example.com/page#") == "https://example.com/page"


def test_combined_normalization() -> None:
    value = canonicalize_url("http://www.example.com//a//?b=2&a=1&utm_source=x#frag")
    assert value == "https://example.com/a?a=1&b=2#frag"


def test_deduplicate_preserves_first_occurrence_order() -> None:
    urls = [
        "https://example.com/b",
        "https://example.com/a",
        "https://example.com/b?utm_source=x",
        "https://other.com/x",
    ]
    assert deduplicate_urls(urls) == ["https://example.com/b", "https://example.com/a", "https://other.com/x"]


def test_deduplicate_keeps_original_string_not_canonical() -> None:
    urls = [
        "http://www.example.com/page/",
        "https://example.com/page?utm_source=1",
        "https://example.com/page",
    ]
    result = deduplicate_urls(urls)
    assert result == ["http://www.example.com/page/"]


def test_deduplicate_scheme_and_slash_variants_collapse() -> None:
    urls = ["http://example.com/page", "https://example.com/page/"]
    assert deduplicate_urls(urls) == ["http://example.com/page"]


def test_deduplicate_empty_list() -> None:
    assert deduplicate_urls([]) == []


def test_edge_case_empty_string_does_not_raise() -> None:
    assert canonicalize_url("") == "https:///"


def test_edge_case_garbage_input_does_not_raise() -> None:
    result = canonicalize_url("garbage input [[[")
    assert isinstance(result, str)
    assert result.startswith("https://")


def test_edge_case_url_without_scheme_does_not_raise() -> None:
    result = canonicalize_url("example.com/page")
    assert isinstance(result, str)
    assert result.startswith("https://")
    assert "example.com/page" in result
