"""
Slack Web API connector for ingesting workspace channels, message threads,
replies, and cross-platform references. Conforms to BaseConnector.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from apps.api.config import settings
from apps.api.connectors.base import (
    BaseConnector,
    ExtractedLink,
    FetchResult,
    NormalizedRecord,
    ValidationResult,
)
from apps.api.connectors.github import extract_references

logger = logging.getLogger(__name__)

# Pattern for Slack permalinks: https://subdomain.slack.com/archives/C12345678/p1698451200123456
_SLACK_ARCHIVE_URL_RE = re.compile(
    r"https?://[a-zA-Z0-9\-]+\.slack\.com/archives/([A-Z0-9]+)/p(\d{10})(\d{6})",
    re.IGNORECASE,
)


def slack_ts_to_datetime(ts_str: Optional[str]) -> datetime:
    """Convert Slack timestamp string (seconds.microseconds) to UTC datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def extract_slack_references(text: str) -> List[ExtractedLink]:
    """
    Extract cross-references from Slack message text:
    - GitHub issues, PRs, and commit SHAs
    - Jira ticket keys
    - Other Slack thread/message archive permalinks
    """
    if not text:
        return []

    # 1. Base references (GitHub & Jira) with provenance 'slack_reference'
    links = extract_references(text, provenance="slack_reference")

    # 2. Slack permalink references
    seen_targets = {l.target_external_id for l in links}
    for match in _SLACK_ARCHIVE_URL_RE.finditer(text):
        channel_id = match.group(1)
        sec = match.group(2)
        mic = match.group(3)
        formatted_ts = f"{sec}.{mic}"
        target_ext_id = f"slack:{channel_id}:{formatted_ts}"
        if target_ext_id not in seen_targets:
            seen_targets.add(target_ext_id)
            links.append(
                ExtractedLink(
                    target_external_id=target_ext_id,
                    link_type="explicit",
                    provenance="slack_reference",
                )
            )

    return links


class SlackConnector(BaseConnector):
    """
    Connector for Slack Web API.
    Ingests message threads and discussions into normalized slack_thread records.
    """

    def __init__(
        self,
        channel_id: str,
        token: Optional[str] = None,
        base_url: str = "https://slack.com/api",
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        """
        :param channel_id: Slack channel ID (e.g. C0123456789).
        :param token: Slack Bot token (xoxb-...) or User token.
        :param base_url: Slack API base URL (defaults to https://slack.com/api).
        :param client: Optional httpx.AsyncClient for testing/mocks.
        """
        if not channel_id or not channel_id.strip():
            raise ValueError("Slack channel_id is required.")

        self.channel_id = channel_id.strip()
        self.base_url = base_url.rstrip("/")

        secret_token = token or (
            settings.slack_bot_token.get_secret_value() if settings.slack_bot_token else None
        )
        self.token = secret_token.strip() if secret_token else None
        self._custom_client = client
        self._user_cache: Dict[str, Dict[str, Optional[str]]] = {}
        self._channel_info: Optional[Dict[str, Any]] = None
        self._team_url: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json; charset=utf-8",
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
        """Validate Slack credentials and channel access permissions."""
        client_to_close = None
        client = self._custom_client
        if client is None:
            client = self._client()
            client_to_close = client

        try:
            # 1. Test authentication identity via auth.test
            auth_resp = await client.post(f"{self.base_url}/auth.test", headers=self._get_headers())
            if auth_resp.status_code != 200:
                return ValidationResult(
                    is_valid=False,
                    message=f"Slack authentication failed: HTTP {auth_resp.status_code}",
                    details={"status_code": auth_resp.status_code},
                )

            auth_data = auth_resp.json()
            if not auth_data.get("ok"):
                err = auth_data.get("error", "unknown_error")
                return ValidationResult(
                    is_valid=False,
                    message=f"Slack authentication rejected: {err}",
                    details={"error": err},
                )

            self._team_url = auth_data.get("url")
            team_name = auth_data.get("team")
            bot_user = auth_data.get("user")

            # 2. Verify channel access via conversations.info
            conv_resp = await client.get(
                f"{self.base_url}/conversations.info",
                params={"channel": self.channel_id},
                headers=self._get_headers(),
            )
            if conv_resp.status_code == 429:
                return ValidationResult(
                    is_valid=False,
                    message="Slack API rate limit exceeded.",
                    details={"rate_limited": True},
                )

            conv_data = conv_resp.json()
            if not conv_data.get("ok"):
                err = conv_data.get("error", "unknown_error")
                if err in ("channel_not_found", "not_in_channel"):
                    return ValidationResult(
                        is_valid=False,
                        message=f"Channel {self.channel_id} not found or bot is not a member. Invite the bot with '/invite @{bot_user}'.",
                        details={"error": err, "channel_id": self.channel_id},
                    )
                elif err == "missing_scope":
                    needed = conv_data.get("needed", "channels:read")
                    return ValidationResult(
                        is_valid=False,
                        message=f"Slack token lacks required permission scope '{needed}'.",
                        details={"error": err, "needed": needed},
                    )
                return ValidationResult(
                    is_valid=False,
                    message=f"Failed accessing channel {self.channel_id}: {err}",
                    details={"error": err},
                )

            self._channel_info = conv_data.get("channel", {})
            channel_name = self._channel_info.get("name", self.channel_id)
            is_private = self._channel_info.get("is_private", False)

            return ValidationResult(
                is_valid=True,
                message=f"Connected to Slack team '{team_name}' as @{bot_user}. Channel #{channel_name} accessible.",
                details={
                    "team": team_name,
                    "team_url": self._team_url,
                    "channel_id": self.channel_id,
                    "channel_name": channel_name,
                    "is_private": is_private,
                },
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                message=f"Slack connection failed: {str(e)}",
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
        Incrementally fetch message threads from the configured channel.
        Uses Slack pagination cursor and `latest_ts` timestamp cursor.
        """
        cursor = cursor or {}
        oldest_ts = cursor.get("latest_ts") or cursor.get("since")
        new_cursor = dict(cursor)
        records: List[NormalizedRecord] = []
        errors: List[str] = []

        client_to_close = None
        client = self._custom_client
        if client is None:
            client = self._client()
            client_to_close = client

        try:
            # Ensure bot joins public channel if permitted
            try:
                await client.post(
                    f"{self.base_url}/conversations.join",
                    json={"channel": self.channel_id},
                    headers=self._get_headers(),
                )
            except Exception:
                pass

            # Resolve channel info if not cached
            channel_name = await self._get_channel_name(client)

            # Paginate through conversations.history
            history_url = f"{self.base_url}/conversations.history"
            page_cursor = cursor.get("next_cursor")
            max_seen_ts: Optional[str] = oldest_ts

            while True:
                params: Dict[str, Any] = {
                    "channel": self.channel_id,
                    "limit": min(100, limit or 50),
                }
                if oldest_ts:
                    params["oldest"] = oldest_ts
                if page_cursor:
                    params["cursor"] = page_cursor

                resp = await client.get(history_url, params=params, headers=self._get_headers())
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After", "30")
                    raise RuntimeError(f"Slack API rate limit exceeded. Retry after {retry_after}s.")

                data = resp.json()
                if not data.get("ok"):
                    err = data.get("error", "unknown_error")
                    self._handle_api_error(err, "conversations.history", data)

                messages = data.get("messages", [])
                if not messages:
                    break

                for msg in messages:
                    # Ignore subtype events that are not user messages (e.g. channel_join)
                    subtype = msg.get("subtype")
                    if subtype in ("channel_join", "channel_leave", "pinned_item"):
                        continue

                    # Process thread or standalone message
                    norm_rec, thread_latest_ts = await self._process_thread(
                        client=client,
                        parent_msg=msg,
                        channel_name=channel_name,
                    )

                    records.append(norm_rec)

                    if thread_latest_ts:
                        if not max_seen_ts or float(thread_latest_ts) > float(max_seen_ts):
                            max_seen_ts = thread_latest_ts

                    if limit is not None and len(records) >= limit:
                        new_cursor["latest_ts"] = max_seen_ts
                        return FetchResult(
                            records=records[:limit],
                            new_cursor=new_cursor,
                            has_more=True,
                            errors=errors,
                        )

                # Pagination
                meta = data.get("response_metadata", {})
                page_cursor = meta.get("next_cursor")
                if not page_cursor or not data.get("has_more", False):
                    break

            if max_seen_ts:
                new_cursor["latest_ts"] = max_seen_ts
                new_cursor["since"] = max_seen_ts
            new_cursor.pop("next_cursor", None)

            return FetchResult(
                records=records,
                new_cursor=new_cursor,
                has_more=False,
                errors=errors,
            )

        except Exception as e:
            logger.exception("Slack fetch failed for channel %s", self.channel_id)
            errors.append(f"Slack fetch failure: {str(e)}")
            return FetchResult(
                records=records,
                new_cursor=new_cursor,
                has_more=False,
                errors=errors,
            )
        finally:
            if client_to_close is not None:
                await client_to_close.aclose()

    async def _process_thread(
        self,
        client: httpx.AsyncClient,
        parent_msg: Dict[str, Any],
        channel_name: str,
    ) -> Tuple[NormalizedRecord, str]:
        """
        Fetch thread replies if present and normalize into a single slack_thread record.
        """
        parent_ts = parent_msg["ts"]
        thread_ts = parent_msg.get("thread_ts", parent_ts)
        is_deleted = parent_msg.get("subtype") == "message_deleted"

        # Resolve parent author
        user_id = parent_msg.get("user")
        author_name, author_email = await self._resolve_user(client, user_id)

        parent_text = parent_msg.get("text", "")
        parent_created_at = slack_ts_to_datetime(parent_ts)

        # Edit timestamp
        edited_info = parent_msg.get("edited")
        parent_updated_at = (
            slack_ts_to_datetime(edited_info.get("ts")) if edited_info else parent_created_at
        )

        max_ts_in_thread = parent_ts
        reply_records: List[Dict[str, Any]] = []

        # If thread has replies, fetch via conversations.replies
        reply_count = parent_msg.get("reply_count", 0)
        if reply_count > 0:
            replies_url = f"{self.base_url}/conversations.replies"
            r_resp = await client.get(
                replies_url,
                params={"channel": self.channel_id, "ts": thread_ts, "limit": 100},
                headers=self._get_headers(),
            )
            if r_resp.status_code == 200:
                r_data = r_resp.json()
                if r_data.get("ok"):
                    all_replies = r_data.get("messages", [])
                    # Skip the first item as it is the parent message
                    for rep in all_replies[1:]:
                        r_ts = rep.get("ts")
                        r_user = rep.get("user")
                        r_author, _ = await self._resolve_user(client, r_user)
                        r_text = rep.get("text", "")
                        r_created = slack_ts_to_datetime(r_ts)
                        r_edited = rep.get("edited")
                        r_updated = slack_ts_to_datetime(r_edited.get("ts")) if r_edited else r_created

                        reply_records.append({
                            "author": r_author,
                            "text": r_text,
                            "created_at": r_created.isoformat(),
                            "ts": r_ts,
                        })

                        if r_ts and float(r_ts) > float(max_ts_in_thread):
                            max_ts_in_thread = r_ts
                        if r_updated > parent_updated_at:
                            parent_updated_at = r_updated

        # Construct unified evidence content
        content_lines = [
            f"# Slack Thread in #{channel_name}",
            f"Channel ID: {self.channel_id} | Thread Root: {thread_ts}",
            f"Author: {author_name or 'Unknown'}",
            f"Created: {parent_created_at.isoformat()} | Updated: {parent_updated_at.isoformat()}",
        ]
        if edited_info:
            content_lines.append("Status: Edited upstream")

        content_lines.append("\n## Initial Message")
        content_lines.append(parent_text if parent_text.strip() else "(Empty message)")

        if reply_records:
            content_lines.append(f"\n## Replies ({len(reply_records)})")
            for rep in reply_records:
                content_lines.append(
                    f"### Reply by {rep['author']} ({rep['created_at']})\n{rep['text']}"
                )

        full_content = "\n".join(content_lines)

        # Extract cross-references
        extracted_links = extract_slack_references(full_content)

        # Format URL / permalink
        raw_permalink = parent_msg.get("permalink")
        if not raw_permalink and self._team_url:
            clean_ts = parent_ts.replace(".", "")
            raw_permalink = f"{self._team_url.rstrip('/')}/archives/{self.channel_id}/p{clean_ts}"

        # Clean title
        first_line = parent_text.strip().split("\n")[0] if parent_text.strip() else "Thread"
        if len(first_line) > 80:
            first_line = first_line[:77] + "..."
        title = f"[#{channel_name}] {first_line}"

        metadata = {
            "channel_id": self.channel_id,
            "channel_name": channel_name,
            "thread_ts": thread_ts,
            "ts": parent_ts,
            "reply_count": len(reply_records),
            "is_edited": bool(edited_info),
        }

        record = NormalizedRecord(
            external_id=f"slack:{self.channel_id}:{thread_ts}",
            record_type="slack_thread",  # Matches schema CHECK constraint
            title=title,
            content=full_content,
            url=raw_permalink,
            author_name=author_name,
            author_email=author_email,
            source_created_at=parent_created_at,
            source_updated_at=parent_updated_at,
            is_deleted_upstream=is_deleted,
            metadata=metadata,
            extracted_links=extracted_links,
        )

        return record, max_ts_in_thread

    async def _resolve_user(
        self,
        client: httpx.AsyncClient,
        user_id: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve Slack user ID to display name and email address with caching."""
        if not user_id:
            return None, None

        if user_id in self._user_cache:
            cached = self._user_cache[user_id]
            return cached.get("name"), cached.get("email")

        try:
            resp = await client.get(
                f"{self.base_url}/users.info",
                params={"user": user_id},
                headers=self._get_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    user_data = data.get("user", {})
                    profile = user_data.get("profile", {})
                    name = profile.get("display_name") or user_data.get("real_name") or user_data.get("name")
                    email = profile.get("email")
                    self._user_cache[user_id] = {"name": name, "email": email}
                    return name, email
        except Exception:
            pass

        self._user_cache[user_id] = {"name": user_id, "email": None}
        return user_id, None

    async def _get_channel_name(self, client: httpx.AsyncClient) -> str:
        """Get channel display name, falling back to channel ID."""
        if self._channel_info and self._channel_info.get("name"):
            return self._channel_info["name"]

        try:
            resp = await client.get(
                f"{self.base_url}/conversations.info",
                params={"channel": self.channel_id},
                headers=self._get_headers(),
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    self._channel_info = data.get("channel", {})
                    return self._channel_info.get("name", self.channel_id)
        except Exception:
            pass

        return self.channel_id

    def _handle_api_error(self, error: str, endpoint: str, data: Dict[str, Any]) -> None:
        """Format detailed API error."""
        if error == "missing_scope":
            needed = data.get("needed", "unknown")
            raise RuntimeError(f"Slack API error in {endpoint}: missing scope '{needed}'.")
        if error == "channel_not_found":
            raise RuntimeError(f"Slack channel '{self.channel_id}' not found or inaccessible.")
        if error == "not_in_channel":
            raise RuntimeError(f"Slack bot is not a member of channel '{self.channel_id}'. Please invite it.")
        raise RuntimeError(f"Slack API error in {endpoint}: {error}")

