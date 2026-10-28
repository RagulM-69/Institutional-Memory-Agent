"""
Jira Cloud REST API connector for ingesting tickets, comments, and issue links.
Conforms to BaseConnector.
"""

from __future__ import annotations

import base64
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
from apps.api.connectors.github import extract_references, parse_iso_datetime

logger = logging.getLogger(__name__)


def adf_to_text(node: Any) -> str:
    """
    Recursively parse Atlassian Document Format (ADF) JSON into readable markdown/plain text.
    Handles plain strings, headings, paragraphs, code blocks, lists, and text nodes.
    """
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        node_type = node.get("type", "")
        text = node.get("text", "")
        content = node.get("content", [])
        inner = "".join(adf_to_text(child) for child in content)

        if node_type == "paragraph":
            return inner.strip() + "\n\n" if inner.strip() else ""
        elif node_type == "heading":
            level = node.get("attrs", {}).get("level", 2)
            return f"{'#' * level} {inner.strip()}\n\n"
        elif node_type == "codeBlock":
            lang = node.get("attrs", {}).get("language", "")
            return f"```{lang}\n{inner.strip()}\n```\n\n"
        elif node_type == "bulletList":
            return inner + "\n"
        elif node_type == "orderedList":
            return inner + "\n"
        elif node_type == "listItem":
            return f"- {inner.strip()}\n"
        elif node_type == "blockquote":
            return f"> {inner.strip()}\n\n"
        elif node_type == "rule":
            return "---\n\n"
        elif node_type == "mention":
            attrs = node.get("attrs", {})
            return f"@{attrs.get('text', attrs.get('id', 'user'))} "
        elif text:
            # Check for link marks
            for mark in node.get("marks", []):
                if mark.get("type") == "link":
                    href = mark.get("attrs", {}).get("href")
                    if href:
                        return f"[{text}]({href})"
            return text
        return inner
    if isinstance(node, list):
        return "".join(adf_to_text(item) for item in node)
    return str(node)


class JiraConnector(BaseConnector):
    """
    Ingests Jira Cloud tickets, descriptions, comments, and relationships.
    Operates incrementally using Jira Cloud REST APIs.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        token: Optional[str] = None,
        project: Optional[str] = None,
        jql: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        raw_url = base_url or settings.jira_base_url
        if not raw_url:
            raise ValueError("Jira base_url is required (either parameter or JIRA_BASE_URL).")

        self.base_url = raw_url.strip().rstrip("/")
        self.email = (email or settings.jira_email or "").strip()
        secret_token = token or (
            settings.jira_token.get_secret_value() if settings.jira_token else None
        )
        self.token = secret_token.strip() if secret_token else None
        self.project = project.strip().upper() if project else None
        self.custom_jql = jql.strip() if jql else None
        self._custom_client = client

    def _get_auth_header(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": "Handoff-Institutional-Memory-Agent/1.0",
        }
        if self.email and self.token:
            auth_bytes = f"{self.email}:{self.token}".encode("utf-8")
            encoded = base64.b64encode(auth_bytes).decode("ascii")
            headers["Authorization"] = f"Basic {encoded}"
        elif self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.AsyncClient(
            headers=self._get_auth_header(),
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
        )

    async def validate(self) -> ValidationResult:
        """Validate Jira Cloud credentials and repository / project reachability."""
        client_to_close = None
        client = self._custom_client
        if client is None:
            client = self._client()
            client_to_close = client

        try:
            # 1. Verify user identity via /rest/api/3/myself (or /rest/api/2/myself)
            myself_url = f"{self.base_url}/rest/api/3/myself"
            headers = self._get_auth_header()
            resp = await client.get(myself_url, headers=headers)

            if resp.status_code == 404:
                # Try v2 endpoint fallback
                myself_url = f"{self.base_url}/rest/api/2/myself"
                resp = await client.get(myself_url, headers=headers)

            if resp.status_code == 200:
                user_data = resp.json()
                display_name = user_data.get("displayName") or user_data.get("name") or "User"
                email = user_data.get("emailAddress", "hidden")

                # 2. If a specific project is configured, verify project access
                project_details = {}
                if self.project:
                    proj_url = f"{self.base_url}/rest/api/3/project/{self.project}"
                    proj_resp = await client.get(proj_url, headers=headers)
                    if proj_resp.status_code == 404:
                        proj_url = f"{self.base_url}/rest/api/2/project/{self.project}"
                        proj_resp = await client.get(proj_url, headers=headers)

                    if proj_resp.status_code == 200:
                        pdata = proj_resp.json()
                        project_details = {
                            "project_key": pdata.get("key"),
                            "project_name": pdata.get("name"),
                        }
                    elif proj_resp.status_code == 404:
                        return ValidationResult(
                            is_valid=False,
                            message=f"Project '{self.project}' not found or token lacks access.",
                            details={"status_code": 404, "project": self.project},
                        )
                    else:
                        return ValidationResult(
                            is_valid=False,
                            message=f"Failed accessing project '{self.project}': HTTP {proj_resp.status_code}",
                            details={"status_code": proj_resp.status_code},
                        )

                return ValidationResult(
                    is_valid=True,
                    message=f"Connected to Jira as {display_name} ({email})."
                    + (f" Project '{self.project}' verified." if self.project else ""),
                    details={
                        "display_name": display_name,
                        "email": email,
                        "base_url": self.base_url,
                        **project_details,
                    },
                )
            elif resp.status_code == 401:
                return ValidationResult(
                    is_valid=False,
                    message="Jira authentication failed. Please verify email and API token.",
                    details={"status_code": 401},
                )
            elif resp.status_code == 403:
                return ValidationResult(
                    is_valid=False,
                    message="Access forbidden to Jira instance.",
                    details={"status_code": 403},
                )
            elif resp.status_code == 429:
                return ValidationResult(
                    is_valid=False,
                    message="Jira API rate limit exceeded.",
                    details={"status_code": 429, "rate_limited": True},
                )
            else:
                return ValidationResult(
                    is_valid=False,
                    message=f"Jira API error during authentication: HTTP {resp.status_code}",
                    details={"status_code": resp.status_code},
                )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                message=f"Jira connection failed: {str(e)}",
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
        Incrementally fetch Jira issues, descriptions, comments, and links.
        Uses `since` timestamp stored in the cursor dictionary.
        """
        cursor = cursor or {}
        since_str = cursor.get("since")
        new_cursor = dict(cursor)
        records: List[NormalizedRecord] = []
        errors: List[str] = []

        client_to_close = None
        client = self._custom_client
        if client is None:
            client = self._client()
            client_to_close = client

        try:
            # Build JQL query
            jql_parts: List[str] = []
            if self.project:
                jql_parts.append(f'project = "{self.project}"')
            if self.custom_jql:
                jql_parts.append(f"({self.custom_jql})")

            since_dt: Optional[datetime] = None
            if since_str:
                since_dt = parse_iso_datetime(since_str)
                # Jira JQL expects "YYYY-MM-DD HH:mm" or "YYYY/MM/DD HH:mm"
                jira_date = since_dt.strftime("%Y-%m-%d %H:%M")
                jql_parts.append(f'updated >= "{jira_date}"')

            jql = " AND ".join(jql_parts) if jql_parts else ""
            if jql:
                jql += " ORDER BY updated ASC"
            else:
                jql = "ORDER BY updated ASC"

            search_url = f"{self.base_url}/rest/api/3/search/jql"
            fields_to_request = [
                "summary",
                "description",
                "status",
                "issuetype",
                "project",
                "reporter",
                "assignee",
                "labels",
                "priority",
                "created",
                "updated",
                "comment",
                "issuelinks",
            ]

            start_at = 0
            page_size = min(100, limit or 50)
            max_updated_at: Optional[str] = since_str

            while True:
                params: Dict[str, Any] = {
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": page_size,
                    "fields": ",".join(fields_to_request),
                }

                resp = await client.get(search_url, params=params, headers=self._get_auth_header())
                if resp.status_code in (404, 410):
                    # Fallback to legacy search endpoint if search/jql not available
                    fallback_url = f"{self.base_url}/rest/api/3/search"
                    fallback_resp = await client.get(fallback_url, params=params, headers=self._get_auth_header())
                    if fallback_resp.status_code in (404, 410):
                        search_url = f"{self.base_url}/rest/api/2/search"
                        resp = await client.get(search_url, params=params, headers=self._get_auth_header())
                    else:
                        search_url = fallback_url
                        resp = fallback_resp

                if resp.status_code != 200:
                    self._handle_http_error(resp)

                data = resp.json()
                issues = data.get("issues", [])
                total = data.get("total", 0)

                if not issues:
                    break

                for issue in issues:
                    norm_rec, issue_updated = self._normalize_issue(issue)

                    # Ensure we don't regress behind since_dt due to JQL minute truncation
                    if since_dt and norm_rec.source_updated_at < since_dt:
                        continue

                    records.append(norm_rec)
                    if issue_updated:
                        if not max_updated_at or issue_updated > max_updated_at:
                            max_updated_at = issue_updated

                    if limit is not None and len(records) >= limit:
                        new_cursor["since"] = max_updated_at
                        return FetchResult(
                            records=records[:limit],
                            new_cursor=new_cursor,
                            has_more=True,
                            errors=errors,
                        )

                start_at += len(issues)
                if start_at >= total or len(issues) < page_size:
                    break

            if max_updated_at:
                new_cursor["since"] = max_updated_at

            return FetchResult(
                records=records,
                new_cursor=new_cursor,
                has_more=False,
                errors=errors,
            )

        except Exception as e:
            logger.exception("Jira fetch failed for %s", self.base_url)
            errors.append(f"Jira fetch failure: {str(e)}")
            return FetchResult(
                records=records,
                new_cursor=new_cursor,
                has_more=False,
                errors=errors,
            )
        finally:
            if client_to_close is not None:
                await client_to_close.aclose()

    def _normalize_issue(self, issue: Dict[str, Any]) -> Tuple[NormalizedRecord, str]:
        """Convert raw Jira issue object into standard NormalizedRecord."""
        key = issue["key"]
        issue_id = issue.get("id")
        fields = issue.get("fields") or {}

        summary = fields.get("summary") or ""
        raw_desc = fields.get("description")
        description_text = adf_to_text(raw_desc).strip()

        # Status & Type
        status_obj = fields.get("status") or {}
        status_name = status_obj.get("name") or "Unknown"

        type_obj = fields.get("issuetype") or {}
        issue_type = type_obj.get("name") or "Ticket"

        # Project
        proj_obj = fields.get("project") or {}
        project_name = proj_obj.get("name") or self.project or "Project"
        project_key = proj_obj.get("key") or (self.project or key.split("-")[0])

        # Priority & Labels
        priority_obj = fields.get("priority") or {}
        priority_name = priority_obj.get("name") or "None"
        labels = fields.get("labels") or []

        # People
        reporter_obj = fields.get("reporter") or {}
        reporter_name = reporter_obj.get("displayName") or reporter_obj.get("name")
        reporter_email = reporter_obj.get("emailAddress")

        assignee_obj = fields.get("assignee") or {}
        assignee_name = assignee_obj.get("displayName") or assignee_obj.get("name")

        # Timestamps
        created_str = fields.get("created")
        updated_str = fields.get("updated")
        created_at = parse_iso_datetime(created_str)
        updated_at = parse_iso_datetime(updated_str)

        # Comments
        comment_container = fields.get("comment") or {}
        raw_comments = comment_container.get("comments") or []
        parsed_comments: List[Dict[str, Any]] = []

        comments_section_parts: List[str] = []
        for c in raw_comments:
            c_id = c.get("id")
            c_author = (c.get("author") or {}).get("displayName") or "Unknown"
            c_created = c.get("created") or ""
            c_body = adf_to_text(c.get("body")).strip()

            parsed_comments.append({
                "id": c_id,
                "author": c_author,
                "created": c_created,
                "body": c_body,
            })
            comments_section_parts.append(
                f"### Comment by {c_author} ({c_created})\n{c_body}"
            )

        # Assemble full evidence text
        content_lines = [
            f"# [{key}] {summary}",
            f"Project: {project_name} ({project_key}) | Type: {issue_type} | Status: {status_name} | Priority: {priority_name}",
            f"Reporter: {reporter_name or 'None'} | Assignee: {assignee_name or 'Unassigned'}",
            f"Created: {created_str} | Updated: {updated_str}",
        ]
        if labels:
            content_lines.append(f"Labels: {', '.join(labels)}")

        content_lines.append("\n## Description")
        content_lines.append(description_text if description_text else "No description provided.")

        if comments_section_parts:
            content_lines.append("\n## Comments")
            content_lines.extend(comments_section_parts)

        content = "\n".join(content_lines)

        # Extract links:
        # 1. Text cross-references (Jira keys, GitHub #123, commit SHAs)
        extracted_links = extract_references(content, provenance="jira_link")

        # 2. Explicit Jira issuelinks
        linked_keys: List[str] = []
        raw_links = fields.get("issuelinks") or []
        for link in raw_links:
            outward = link.get("outwardIssue")
            inward = link.get("inwardIssue")
            if outward and "key" in outward:
                lk = outward["key"]
                linked_keys.append(lk)
                extracted_links.append(
                    ExtractedLink(
                        target_external_id=f"jira:{lk}",
                        link_type="explicit",
                        provenance="jira_link",
                    )
                )
            if inward and "key" in inward:
                lk = inward["key"]
                linked_keys.append(lk)
                extracted_links.append(
                    ExtractedLink(
                        target_external_id=f"jira:{lk}",
                        link_type="explicit",
                        provenance="jira_link",
                    )
                )

        # Deduplicate links
        seen_targets = set()
        deduped_links: List[ExtractedLink] = []
        for l in extracted_links:
            # Avoid self-reference
            if l.target_external_id in (f"jira:{key}", f"ticket:{key}"):
                continue
            key_tuple = (l.target_external_id, l.link_type, l.provenance)
            if key_tuple not in seen_targets:
                seen_targets.add(key_tuple)
                deduped_links.append(l)

        url = f"{self.base_url}/browse/{key}"

        metadata = {
            "key": key,
            "id": issue_id,
            "project_key": project_key,
            "issue_type": issue_type,
            "status": status_name,
            "priority": priority_name,
            "labels": labels,
            "assignee": assignee_name,
            "comments_count": len(parsed_comments),
            "linked_keys": linked_keys,
            "html_url": url,
        }

        record = NormalizedRecord(
            external_id=f"jira:{key}",
            record_type="ticket",  # Aligns with schema CHECK constraint
            title=f"[{key}] {summary}",
            content=content,
            url=url,
            author_name=reporter_name,
            author_email=reporter_email,
            source_created_at=created_at,
            source_updated_at=updated_at,
            is_deleted_upstream=False,
            metadata=metadata,
            extracted_links=deduped_links,
        )

        return record, updated_str or ""

    def _handle_http_error(self, resp: httpx.Response) -> None:
        """Raise formatted exception on Jira HTTP error."""
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "unknown")
            raise RuntimeError(f"Jira API rate limit exceeded. Retry after: {retry_after}s.")
        if resp.status_code == 401:
            raise RuntimeError("Jira API authentication failed (HTTP 401).")
        if resp.status_code == 403:
            raise RuntimeError("Jira API access forbidden (HTTP 403).")
        if resp.status_code == 400:
            raise RuntimeError(f"Jira API bad request (HTTP 400): {resp.text[:300]}")
        raise RuntimeError(f"Jira API error HTTP {resp.status_code}: {resp.text[:300]}")

