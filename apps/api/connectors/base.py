"""
Base abstractions and standardized data structures for source connectors.
Every external platform connector (GitHub, Jira, Slack) conforms to this contract.
Connectors strictly extract and normalize external data; they do not write directly to the database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ExtractedLink:
    """
    Cross-reference extracted from record content (e.g. #123, commit SHA, PR link).
    The ingestion pipeline resolves target_external_id to an internal record_id.
    """
    target_external_id: str
    link_type: str = "explicit"  # 'explicit', 'human_confirmed', 'inferred'
    provenance: str = "commit_message"  # 'commit_message', 'jira_link', 'slack_reference', 'pr_description', 'user_action'


@dataclass
class NormalizedRecord:
    """Standardized representation of an upstream entity."""
    external_id: str
    record_type: str  # 'commit', 'pull_request', 'review_comment', 'issue', 'ticket', 'slack_thread', 'meeting'
    title: str
    content: str
    source_created_at: datetime
    source_updated_at: datetime
    url: Optional[str] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    is_deleted_upstream: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    extracted_links: List[ExtractedLink] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of connector authentication and source reachability validation."""
    is_valid: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """Standard payload returned by a connector fetch execution."""
    records: List[NormalizedRecord]
    new_cursor: Dict[str, Any] = field(default_factory=dict)
    has_more: bool = False
    errors: List[str] = field(default_factory=list)


class BaseConnector(ABC):
    """Abstract base class for all source connectors."""

    @abstractmethod
    async def validate(self) -> ValidationResult:
        """Validate credentials, repository / workspace access, and API readiness."""
        ...

    @abstractmethod
    async def fetch(
        self,
        cursor: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> FetchResult:
        """
        Fetch incremental updates since cursor up to optional limit.
        Returns normalized records and the updated sync cursor.
        """
        ...

