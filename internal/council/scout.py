"""
DeSearch/SN22 Scout mode for the Council engine.

Provides search capabilities across multiple sources:
- Web search
- X (Twitter)
- TikTok
- Telegram
- On-chain data

Results are normalized and can be stored as evidence in the trace store.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.trace_store import get_trace_store

# Default sources to search
DEFAULT_SOURCES = ["web", "x", "tiktok", "telegram", "onchain"]


@dataclass
class SearchQuery:
    """A search query for the DeSearch scout."""
    query: str
    sources: List[str] = field(default_factory=lambda: DEFAULT_SOURCES)
    limit: int = 10
    netuid: Optional[int] = None


@dataclass
class SourceHit:
    """A single search result from a source."""
    source: str
    url: Optional[str]
    title: Optional[str]
    content: Optional[str]
    timestamp: str
    query: str = ""  # The query that produced this hit
    author: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchFinding:
    """A normalized search finding with relevance score."""
    query: str
    source: str
    url: Optional[str]
    title: Optional[str]
    content: Optional[str]
    relevance_score: float
    timestamp: str
    author: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _hash_content(content: str) -> str:
    """Hash content for deduplication."""
    return hashlib.md5(content.encode()).hexdigest()[:12]


def _normalize_hit(hit: SourceHit) -> SearchFinding:
    """Normalize a source hit to a search finding."""
    # Calculate relevance score based on content match
    score = 0.5  # Default score
    
    if hit.content:
        # Simple relevance: presence of query terms
        query_terms = hit.query.lower().split()
        content_lower = hit.content.lower()
        matches = sum(1 for term in query_terms if term in content_lower)
        score = min(1.0, matches / max(len(query_terms), 1) + 0.3)
    
    return SearchFinding(
        query=hit.query,
        source=hit.source,
        url=hit.url,
        title=hit.title,
        content=hit.content,
        relevance_score=round(score, 3),
        timestamp=hit.timestamp,
        author=hit.author,
        metadata=hit.metadata,
    )


def _search_web(query: str, limit: int = 10) -> List[SourceHit]:
    """Search the web (stub implementation)."""
    # In production, this would call a real search API
    # For now, return empty results
    return []


def _search_x(query: str, limit: int = 10) -> List[SourceHit]:
    """Search X (Twitter) (stub implementation)."""
    return []


def _search_tiktok(query: str, limit: int = 10) -> List[SourceHit]:
    """Search TikTok (stub implementation)."""
    return []


def _search_telegram(query: str, limit: int = 10) -> List[SourceHit]:
    """Search Telegram (stub implementation)."""
    return []


def _search_onchain(query: str, limit: int = 10) -> List[SourceHit]:
    """Search on-chain data (stub implementation)."""
    return []


_SOURCE_SEARCHERS = {
    "web": _search_web,
    "x": _search_x,
    "tiktok": _search_tiktok,
    "telegram": _search_telegram,
    "onchain": _search_onchain,
}


def run_scout_search(query: SearchQuery) -> List[Dict[str, Any]]:
    """
    Run a search query across specified sources.
    
    Returns normalized findings sorted by relevance.
    """
    all_hits: List[SourceHit] = []
    
    for source in query.sources:
        searcher = _SOURCE_SEARCHERS.get(source)
        if searcher:
            try:
                hits = searcher(query.query, limit=query.limit)
                all_hits.extend(hits)
            except Exception:
                pass
    
    # Normalize and deduplicate
    findings: Dict[str, SearchFinding] = {}
    for hit in all_hits:
        finding = _normalize_hit(hit)
        key = _hash_content(finding.content or finding.title or "")
        if key not in findings or findings[key].relevance_score < finding.relevance_score:
            findings[key] = finding
    
    # Sort by relevance
    sorted_findings = sorted(findings.values(), key=lambda f: f.relevance_score, reverse=True)
    
    # Store in trace as evidence
    store = get_trace_store()
    for finding in sorted_findings[:query.limit]:
        try:
            store.add_evidence(
                run_id=None,
                source=finding.source,
                url=finding.url,
                title=finding.title,
                content=finding.content,
                relevance_score=finding.relevance_score,
                metadata=finding.metadata,
            )
        except Exception:
            pass
    
    return [
        {
            "source": f.source,
            "url": f.url,
            "title": f.title,
            "content": f.content,
            "relevance_score": f.relevance_score,
            "timestamp": f.timestamp,
            "author": f.author,
            "metadata": f.metadata,
        }
        for f in sorted_findings[:query.limit]
    ]


def search_and_store(
    query: str,
    sources: Optional[List[str]] = None,
    limit: int = 10,
    run_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search and store results as evidence in the trace.
    
    Returns the findings.
    """
    search_query = SearchQuery(
        query=query,
        sources=sources or DEFAULT_SOURCES,
        limit=limit,
    )
    
    findings = run_scout_search(search_query)
    
    # Link to run if provided
    if run_id and findings:
        store = get_trace_store()
        for finding in findings:
            try:
                store.add_evidence(
                    run_id=run_id,
                    source=finding["source"],
                    url=finding.get("url"),
                    title=finding.get("title"),
                    content=finding.get("content"),
                    relevance_score=finding.get("relevance_score"),
                    metadata=finding.get("metadata"),
                )
            except Exception:
                pass
    
    return findings