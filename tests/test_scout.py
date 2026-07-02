"""
Tests for the DeSearch Scout module.
"""

import pytest
from internal.council.scout import (
    SearchQuery,
    SourceHit,
    SearchFinding,
    _normalize_hit,
    run_scout_search,
    search_and_store,
)


def test_search_query_defaults():
    """Test SearchQuery default values."""
    query = SearchQuery(query="test")
    assert query.query == "test"
    assert query.sources == ["web", "x", "tiktok", "telegram", "onchain"]
    assert query.limit == 10
    assert query.netuid is None


def test_search_query_custom_sources():
    """Test SearchQuery with custom sources."""
    query = SearchQuery(query="test", sources=["web", "x"], limit=5)
    assert query.sources == ["web", "x"]
    assert query.limit == 5


def test_source_hit_creation():
    """Test SourceHit dataclass creation."""
    hit = SourceHit(
        source="web",
        url="https://example.com",
        title="Test Title",
        content="Test content",
        timestamp="2024-01-01T00:00:00Z",
    )
    assert hit.source == "web"
    assert hit.url == "https://example.com"
    assert hit.title == "Test Title"
    assert hit.content == "Test content"


def test_search_finding_creation():
    """Test SearchFinding dataclass creation."""
    finding = SearchFinding(
        query="test",
        source="web",
        url="https://example.com",
        title="Test",
        content="Content",
        relevance_score=0.85,
        timestamp="2024-01-01T00:00:00Z",
    )
    assert finding.query == "test"
    assert finding.relevance_score == 0.85


def test_normalize_hit_basic():
    """Test normalizing a source hit."""
    hit = SourceHit(
        source="web",
        url="https://example.com",
        title="Test",
        content="This is test content about bitcoin",
        timestamp="2024-01-01T00:00:00Z",
        query="bitcoin",
    )
    finding = _normalize_hit(hit)
    assert finding.source == "web"
    assert finding.url == "https://example.com"
    assert finding.relevance_score > 0.5  # Should have high relevance for matching query


def test_run_scout_search_returns_list():
    """Test that run_scout_search returns a list."""
    query = SearchQuery(query="test", sources=["web"], limit=5)
    results = run_scout_search(query)
    assert isinstance(results, list)


def test_search_and_store_returns_list():
    """Test that search_and_store returns a list."""
    results = search_and_store("test query", sources=["web"], limit=5)
    assert isinstance(results, list)


def test_search_finding_to_dict():
    """Test SearchFinding can be converted to dict."""
    finding = SearchFinding(
        query="test",
        source="web",
        url="https://example.com",
        title="Test",
        content="Content",
        relevance_score=0.85,
        timestamp="2024-01-01T00:00:00Z",
    )
    d = {
        "source": finding.source,
        "url": finding.url,
        "title": finding.title,
        "content": finding.content,
        "relevance_score": finding.relevance_score,
    }
    assert d["source"] == "web"
    assert d["relevance_score"] == 0.85