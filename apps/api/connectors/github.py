"""
GitHub REST API connector for ingesting issues, pull requests, review comments,
issue comments, and commits. Conforms to BaseConnector.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from apps.api.config import settings
from apps.api.connectors.base import (
    BaseConnector,
    ExtractedLink,
    FetchResult,
    NormalizedRecord,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Pattern for GitHub issue/PR cross-references: #123, fixes #123, closes #123
_ISSUE_REF_RE = re.compile(r"(?:fixes|closes|resolves|refs?|see)?\s*#(\d+)\b", re.IGNORECASE)

# Pattern for full GitHub issue/PR URLs
_GITHUB_URL_RE = re.compile(
    r"https?://github\.com/[^/\s]+/[^/\s]+/(?:issues|pull)/(\d+)", re.IGNORECASE
)

# Pattern for Jira ticket keys (e.g. PROJ-1234, ENG-56)
_JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

# Pattern for 40-character commit SHAs
_COMMIT_SHA_RE = re.compile(r"\b([0-9a-f]{40})\b", re.IGNORECASE)


def parse_iso_datetime(dt_str: Optional[str]) -> datetime:
    """Parse ISO8601 string from GitHub API into UTC datetime."""
    if not dt_str:
        return datetime.now(timezone.utc)
    # GitHub timestamps are formatted as 2026-10-27T18:00:00Z
    dt_str = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        return datetime.now(timezone.utc)


def extract_references(text: str, provenance: str) -> List[ExtractedLink]:
    """
    Extract issue/PR references, Jira ticket keys, and commit SHAs from text.
    """
    if not text:
        return []

    links: List[ExtractedLink] = []
    seen: set[Tuple[str, str]] = set()

    def add_link(target: str, link_type: str, prov: str):
        key = (target, link_type)
        if key not in seen:
            seen.add(key)
            links.append(ExtractedLink(target_external_id=target, link_type=link_type, provenance=prov))

    # 1. #123 references: can be issue:123 or pr:123
    for match in _ISSUE_REF_RE.finditer(text):
        num = match.group(1)
        add_link(f"issue:{num}", "explicit", provenance)
        add_link(f"pr:{num}", "explicit", provenance)

    # 2. GitHub issue/PR URLs
    for match in _GITHUB_URL_RE.finditer(text):
        num = match.group(1)
        add_link(f"issue:{num}", "explicit", provenance)
        add_link(f"pr:{num}", "explicit", provenance)

    # 3. Jira ticket keys
    for match in _JIRA_KEY_RE.finditer(text):
        jira_key = match.group(1)
        add_link(f"jira:{jira_key}", "explicit", "jira_link" if "jira" in provenance else provenance)

    # 4. Commit SHAs (full 40-char)
    for match in _COMMIT_SHA_RE.finditer(text):
        sha = match.group(1).lower()
        add_link(f"commit:{sha}", "explicit", provenance)

    return links


class GitHubConnector(BaseConnector):
    """
    Ingests repository artifacts from GitHub REST API.
    Operates incrementally using timestamps.
    """

    def __init__(
        self,
        repo: str,
        token: Optional[str] = None,
        base_url: str = "https://api.github.com",
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """
        :param repo: "owner/repo" format.
        :param token: Personal Access Token or GitHub App token. If None, reads from settings.
        :param base_url: GitHub API base URL (can be overridden for mocks / GitHub Enterprise).
        :param client: Optional httpx.AsyncClient for connection reuse or testing.
        """
        parts = repo.strip().strip("/").split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid repository format '{repo}'. Expected 'owner/repo'.")

        self.owner = parts[0]
        self.repo_name = parts[1]
        self.full_name = f"{self.owner}/{self.repo_name}"
        self.base_url = base_url.rstrip("/")

        secret_token = token or (
            settings.github_token.get_secret_value() if settings.github_token else None
        )
        self.token = secret_token.strip() if secret_token else None
        self._custom_client = client

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Handoff-Institutional-Memory-Agent/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.AsyncClient(
            headers=self._get_headers(),
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
        )

    async def validate(self) -> ValidationResult:
        """Validate repository existence and access permissions."""
        url = f"{self.base_url}/repos/{self.owner}/{self.repo_name}"
        client_to_close = None
        client = self._custom_client
        if client is None:
            client = self._client()
            client_to_close = client

        try:
            resp = await client.get(url, headers=self._get_headers())
            if resp.status_code == 200:
                data = resp.json()
                return ValidationResult(
                    is_valid=True,
                    message=f"Repository {self.full_name} is accessible.",
                    details={
                        "full_name": data.get("full_name"),
                        "private": data.get("private", False),
                        "default_branch": data.get("default_branch", "main"),
                        "description": data.get("description"),
                    },
                )
            elif resp.status_code == 401:
                return ValidationResult(
                    is_valid=False,
                    message="GitHub authentication failed. Please check configured credentials.",
                    details={"status_code": 401},
                )
            elif resp.status_code == 403:
                rate_limit_remaining = resp.headers.get("x-ratelimit-remaining")
                if rate_limit_remaining == "0":
                    reset_time = resp.headers.get("x-ratelimit-reset", "unknown")
                    return ValidationResult(
                        is_valid=False,
                        message=f"GitHub API rate limit exceeded. Reset at {reset_time}.",
                        details={"status_code": 403, "rate_limited": True},
                    )
                return ValidationResult(
                    is_valid=False,
                    message=f"Access forbidden to repository {self.full_name}.",
                    details={"status_code": 403},
                )
            elif resp.status_code == 404:
                return ValidationResult(
                    is_valid=False,
                    message=f"Repository {self.full_name} not found or token lacks access.",
                    details={"status_code": 404},
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    message=f"GitHub API returned unexpected status {resp.status_code}.",
                    details={"status_code": resp.status_code},
                )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                message=f"Connection failed: {str(e)}",
                details={"error": str(e)},
            )
        finally:
            if client_to_close is not None:
                await client_to_close.aclose()

    async def fetch(
        self,
        cursor: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> FetchResult:
        """
        Incrementally fetch issues, pull requests, comments, and commits.
        Uses `since` timestamps stored in the cursor dictionary.
        """
        cursor = cursor or {}
        records: List[NormalizedRecord] = []
        errors: List[str] = []

        client_to_close = None
        client = self._custom_client
        if client is None:
            client = self._client()
            client_to_close = client

        try:
            # Per-stream high-water marks from cursor
            issues_since = cursor.get("issues_since")
            commits_since = cursor.get("commits_since")
            review_comments_since = cursor.get("review_comments_since")
            issue_comments_since = cursor.get("issue_comments_since")

            # Fallback to general `since` if per-stream is missing
            general_since = cursor.get("since")
            if general_since:
                issues_since = issues_since or general_since
                commits_since = commits_since or general_since
                review_comments_since = review_comments_since or general_since
                issue_comments_since = issue_comments_since or general_since

            new_cursor = dict(cursor)

            # 1. Fetch Issues and Pull Requests
            try:
                iss_records, latest_iss = await self._fetch_issues_and_prs(
                    client, since=issues_since, limit=limit
                )
                records.extend(iss_records)
                if latest_iss:
                    new_cursor["issues_since"] = latest_iss
            except Exception as e:
                logger.error("Failed fetching issues for %s: %s", self.full_name, e)
                errors.append(f"Issues: {str(e)}")

            # Check if limit reached
            if limit is not None and len(records) >= limit:
                return FetchResult(
                    records=records[:limit],
                    new_cursor=new_cursor,
                    has_more=True,
                    errors=errors,
                )

            # 2. Fetch Review Comments (diff comments on PRs)
            remaining_limit = None if limit is None else max(0, limit - len(records))
            try:
                rc_records, latest_rc = await self._fetch_review_comments(
                    client, since=review_comments_since, limit=remaining_limit
                )
                records.extend(rc_records)
                if latest_rc:
                    new_cursor["review_comments_since"] = latest_rc
            except Exception as e:
                logger.error("Failed fetching review comments for %s: %s", self.full_name, e)
                errors.append(f"Review Comments: {str(e)}")

            if limit is not None and len(records) >= limit:
                return FetchResult(
                    records=records[:limit],
                    new_cursor=new_cursor,
                    has_more=True,
                    errors=errors,
                )

            # 3. Fetch Issue / PR Comments
            remaining_limit = None if limit is None else max(0, limit - len(records))
            try:
                ic_records, latest_ic = await self._fetch_issue_comments(
                    client, since=issue_comments_since, limit=remaining_limit
                )
                records.extend(ic_records)
                if latest_ic:
                    new_cursor["issue_comments_since"] = latest_ic
            except Exception as e:
                logger.error("Failed fetching issue comments for %s: %s", self.full_name, e)
                errors.append(f"Issue Comments: {str(e)}")

            if limit is not None and len(records) >= limit:
                return FetchResult(
                    records=records[:limit],
                    new_cursor=new_cursor,
                    has_more=True,
                    errors=errors,
                )

            # 4. Fetch Commits
            remaining_limit = None if limit is None else max(0, limit - len(records))
            try:
                commit_records, latest_commit = await self._fetch_commits(
                    client, since=commits_since, limit=remaining_limit
                )
                records.extend(commit_records)
                if latest_commit:
                    new_cursor["commits_since"] = latest_commit
            except Exception as e:
                logger.error("Failed fetching commits for %s: %s", self.full_name, e)
                errors.append(f"Commits: {str(e)}")

            # Update overall high-water mark timestamp
            all_timestamps = [
                ts for ts in [
                    new_cursor.get("issues_since"),
                    new_cursor.get("review_comments_since"),
                    new_cursor.get("issue_comments_since"),
                    new_cursor.get("commits_since"),
                ] if ts
            ]
            if all_timestamps:
                new_cursor["since"] = max(all_timestamps)

            return FetchResult(
                records=records[:limit] if limit is not None else records,
                new_cursor=new_cursor,
                has_more=False,
                errors=errors,
            )
        finally:
            if client_to_close is not None:
                await client_to_close.aclose()

    async def _fetch_issues_and_prs(
        self,
        client: httpx.AsyncClient,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[NormalizedRecord], Optional[str]]:
        """Fetch both issues and pull requests via /issues endpoint."""
        url = f"{self.base_url}/repos/{self.owner}/{self.repo_name}/issues"
        params: Dict[str, Any] = {
            "state": "all",
            "sort": "updated",
            "direction": "asc",
            "per_page": min(100, limit or 100),
        }
        if since:
            params["since"] = since

        records: List[NormalizedRecord] = []
        max_updated_at: Optional[str] = None

        page = 1
        while True:
            params["page"] = page
            resp = await client.get(url, params=params, headers=self._get_headers())
            if resp.status_code != 200:
                self._handle_http_error(resp, "issues")

            items = resp.json()
            if not items:
                break

            for item in items:
                is_pr = "pull_request" in item
                record_type = "pull_request" if is_pr else "issue"
                number = item["number"]
                external_id = f"pr:{number}" if is_pr else f"issue:{number}"

                title = item.get("title", "")
                body = item.get("body") or ""
                state = item.get("state", "open")
                author = item.get("user") or {}
                author_name = author.get("login")
                author_email = None

                created_at = parse_iso_datetime(item.get("created_at"))
                updated_at = parse_iso_datetime(item.get("updated_at"))

                content_parts = [
                    f"# {title}",
                    f"State: {state} | Number: #{number} | Type: {record_type.capitalize()}",
                    f"Author: {author_name}",
                    f"Created: {item.get('created_at')} | Updated: {item.get('updated_at')}",
                ]
                labels = [label["name"] for label in item.get("labels", []) if "name" in label]
                if labels:
                    content_parts.append(f"Labels: {', '.join(labels)}")
                if body.strip():
                    content_parts.append("\n" + body)

                content = "\n".join(content_parts)
                provenance = "pr_description" if is_pr else "issue"
                links = extract_references(f"{title}\n{body}", provenance=provenance)

                metadata = {
                    "number": number,
                    "state": state,
                    "labels": labels,
                    "is_pull_request": is_pr,
                    "html_url": item.get("html_url"),
                    "comments_count": item.get("comments", 0),
                }

                records.append(
                    NormalizedRecord(
                        external_id=external_id,
                        record_type=record_type,
                        title=f"{'PR' if is_pr else 'Issue'} #{number}: {title}",
                        content=content,
                        url=item.get("html_url"),
                        author_name=author_name,
                        author_email=author_email,
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        is_deleted_upstream=False,
                        metadata=metadata,
                        extracted_links=links,
                    )
                )

                if item.get("updated_at"):
                    max_updated_at = item["updated_at"]

                if limit is not None and len(records) >= limit:
                    return records, max_updated_at

            if len(items) < params["per_page"]:
                break
            page += 1

        return records, max_updated_at

    async def _fetch_review_comments(
        self,
        client: httpx.AsyncClient,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[NormalizedRecord], Optional[str]]:
        """Fetch line-level pull request review comments."""
        url = f"{self.base_url}/repos/{self.owner}/{self.repo_name}/pulls/comments"
        params: Dict[str, Any] = {
            "sort": "updated",
            "direction": "asc",
            "per_page": min(100, limit or 100),
        }
        if since:
            params["since"] = since

        records: List[NormalizedRecord] = []
        max_updated_at: Optional[str] = None

        page = 1
        while True:
            params["page"] = page
            resp = await client.get(url, params=params, headers=self._get_headers())
            if resp.status_code != 200:
                self._handle_http_error(resp, "pull request review comments")

            items = resp.json()
            if not items:
                break

            for item in items:
                comment_id = item["id"]
                external_id = f"review_comment:{comment_id}"

                body = item.get("body") or ""
                path = item.get("path", "")
                diff_hunk = item.get("diff_hunk", "")
                commit_id = item.get("commit_id", "")
                author = item.get("user") or {}
                author_name = author.get("login")

                created_at = parse_iso_datetime(item.get("created_at"))
                updated_at = parse_iso_datetime(item.get("updated_at"))

                # Determine parent PR number from pull_request_url
                pr_url = item.get("pull_request_url", "")
                pr_number = pr_url.split("/")[-1] if pr_url else ""

                content_parts = [
                    f"# Review Comment on {path} (PR #{pr_number})",
                    f"Author: {author_name} | Commit: {commit_id[:10] if commit_id else 'unknown'}",
                ]
                if diff_hunk:
                    content_parts.append(f"```diff\n{diff_hunk}\n```")
                if body.strip():
                    content_parts.append(body)

                content = "\n".join(content_parts)
                links = extract_references(body, provenance="review_comment")
                if pr_number and pr_number.isdigit():
                    links.append(
                        ExtractedLink(
                            target_external_id=f"pr:{pr_number}",
                            link_type="explicit",
                            provenance="review_comment",
                        )
                    )
                if commit_id:
                    links.append(
                        ExtractedLink(
                            target_external_id=f"commit:{commit_id.lower()}",
                            link_type="explicit",
                            provenance="review_comment",
                        )
                    )

                metadata = {
                    "comment_id": comment_id,
                    "pr_number": int(pr_number) if pr_number.isdigit() else None,
                    "path": path,
                    "commit_id": commit_id,
                    "html_url": item.get("html_url"),
                }

                records.append(
                    NormalizedRecord(
                        external_id=external_id,
                        record_type="review_comment",
                        title=f"Review comment by {author_name} on {path}",
                        content=content,
                        url=item.get("html_url"),
                        author_name=author_name,
                        author_email=None,
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        is_deleted_upstream=False,
                        metadata=metadata,
                        extracted_links=links,
                    )
                )

                if item.get("updated_at"):
                    max_updated_at = item["updated_at"]

                if limit is not None and len(records) >= limit:
                    return records, max_updated_at

            if len(items) < params["per_page"]:
                break
            page += 1

        return records, max_updated_at

    async def _fetch_issue_comments(
        self,
        client: httpx.AsyncClient,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[NormalizedRecord], Optional[str]]:
        """Fetch general discussion comments on issues and pull requests."""
        url = f"{self.base_url}/repos/{self.owner}/{self.repo_name}/issues/comments"
        params: Dict[str, Any] = {
            "sort": "updated",
            "direction": "asc",
            "per_page": min(100, limit or 100),
        }
        if since:
            params["since"] = since

        records: List[NormalizedRecord] = []
        max_updated_at: Optional[str] = None

        page = 1
        while True:
            params["page"] = page
            resp = await client.get(url, params=params, headers=self._get_headers())
            if resp.status_code != 200:
                self._handle_http_error(resp, "issue comments")

            items = resp.json()
            if not items:
                break

            for item in items:
                comment_id = item["id"]
                external_id = f"comment:{comment_id}"

                body = item.get("body") or ""
                author = item.get("user") or {}
                author_name = author.get("login")

                created_at = parse_iso_datetime(item.get("created_at"))
                updated_at = parse_iso_datetime(item.get("updated_at"))

                # Parent issue / PR URL
                issue_url = item.get("issue_url", "")
                issue_number = issue_url.split("/")[-1] if issue_url else ""

                content_parts = [
                    f"# Comment on #{issue_number}",
                    f"Author: {author_name} | Updated: {item.get('updated_at')}",
                    "\n" + body,
                ]
                content = "\n".join(content_parts)

                links = extract_references(body, provenance="issue_comment")
                if issue_number and issue_number.isdigit():
                    links.append(
                        ExtractedLink(
                            target_external_id=f"issue:{issue_number}",
                            link_type="explicit",
                            provenance="issue_comment",
                        )
                    )
                    links.append(
                        ExtractedLink(
                            target_external_id=f"pr:{issue_number}",
                            link_type="explicit",
                            provenance="issue_comment",
                        )
                    )

                metadata = {
                    "comment_id": comment_id,
                    "issue_number": int(issue_number) if issue_number.isdigit() else None,
                    "html_url": item.get("html_url"),
                }

                # Note: record_type 'issue' matches schema check constraint
                records.append(
                    NormalizedRecord(
                        external_id=external_id,
                        record_type="issue",
                        title=f"Comment on #{issue_number} by {author_name}",
                        content=content,
                        url=item.get("html_url"),
                        author_name=author_name,
                        author_email=None,
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        is_deleted_upstream=False,
                        metadata=metadata,
                        extracted_links=links,
                    )
                )

                if item.get("updated_at"):
                    max_updated_at = item["updated_at"]

                if limit is not None and len(records) >= limit:
                    return records, max_updated_at

            if len(items) < params["per_page"]:
                break
            page += 1

        return records, max_updated_at

    async def _fetch_commits(
        self,
        client: httpx.AsyncClient,
        since: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[NormalizedRecord], Optional[str]]:
        """Fetch commit history."""
        url = f"{self.base_url}/repos/{self.owner}/{self.repo_name}/commits"
        params: Dict[str, Any] = {
            "per_page": min(100, limit or 100),
        }
        if since:
            params["since"] = since

        records: List[NormalizedRecord] = []
        max_updated_at: Optional[str] = None

        page = 1
        while True:
            params["page"] = page
            resp = await client.get(url, params=params, headers=self._get_headers())
            if resp.status_code != 200:
                self._handle_http_error(resp, "commits")

            items = resp.json()
            if not items:
                break

            for item in items:
                sha = item["sha"]
                external_id = f"commit:{sha}"

                commit_info = item.get("commit") or {}
                author_info = commit_info.get("author") or {}
                committer_info = commit_info.get("committer") or {}

                author_name = author_info.get("name") or (item.get("author") or {}).get("login")
                author_email = author_info.get("email")
                message = commit_info.get("message") or ""

                created_str = author_info.get("date") or committer_info.get("date")
                created_at = parse_iso_datetime(created_str)
                # Commits in git are immutable, created_at is updated_at
                updated_at = created_at

                first_line = message.strip().split("\n")[0] if message else "Commit"
                title = f"Commit {sha[:8]}: {first_line}"

                content = f"# Commit {sha}\nAuthor: {author_name} <{author_email}>\nDate: {created_str}\n\n{message}"

                links = extract_references(message, provenance="commit_message")

                metadata = {
                    "sha": sha,
                    "html_url": item.get("html_url"),
                    "parents": [p.get("sha") for p in item.get("parents", []) if "sha" in p],
                }

                records.append(
                    NormalizedRecord(
                        external_id=external_id,
                        record_type="commit",
                        title=title,
                        content=content,
                        url=item.get("html_url"),
                        author_name=author_name,
                        author_email=author_email,
                        source_created_at=created_at,
                        source_updated_at=updated_at,
                        is_deleted_upstream=False,
                        metadata=metadata,
                        extracted_links=links,
                    )
                )

                if created_str:
                    max_updated_at = created_str

                if limit is not None and len(records) >= limit:
                    return records, max_updated_at

            if len(items) < params["per_page"]:
                break
            page += 1

        return records, max_updated_at

    def _handle_http_error(self, resp: httpx.Response, resource_name: str) -> None:
        """Format helpful error message on GitHub API failure."""
        rate_limit_remaining = resp.headers.get("x-ratelimit-remaining")
        if resp.status_code == 403 and rate_limit_remaining == "0":
            reset_time = resp.headers.get("x-ratelimit-reset", "unknown")
            raise RuntimeError(f"GitHub API rate limit exceeded while fetching {resource_name}. Resets at {reset_time}.")
        raise RuntimeError(
            f"GitHub API error fetching {resource_name}: HTTP {resp.status_code} - {resp.text[:200]}"
        )

