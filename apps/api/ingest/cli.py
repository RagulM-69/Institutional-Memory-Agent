"""
Command Line Interface for running evidence ingestion pipelines (GitHub, Jira & Slack).

Usage:
    # GitHub:
    python -m apps.api.ingest.cli --repo owner/repo --org-id <uuid> [--source-id <uuid>] [--limit <int>] [--dry-run]

    # Jira:
    python -m apps.api.ingest.cli --jira-project PROJ --org-id <uuid> [--jira-url <url>] [--limit <int>] [--dry-run]

    # Slack:
    python -m apps.api.ingest.cli --slack-channel C012345 --org-id <uuid> [--limit <int>] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional
from uuid import UUID

from apps.api.config import settings
from apps.api.connectors.github import GitHubConnector
from apps.api.connectors.jira import JiraConnector
from apps.api.connectors.slack import SlackConnector
from apps.api.db.pool import (
    close_pool,
    get_connection,
    get_worker_connection,
    worker_transaction_context,
)
from apps.api.ingest.pipeline import IngestPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("handoff.ingest.cli")


async def resolve_or_create_github_source(
    org_id: UUID,
    repo: str,
    source_id: Optional[UUID] = None,
    create_if_missing: bool = True,
) -> UUID:
    """Find or register a GitHub source under org_id."""
    async with worker_transaction_context(org_id) as conn:
        if source_id is not None:
            row = await conn.fetchrow(
                "SELECT id FROM public.sources WHERE id = $1 AND org_id = $2 AND type = 'github'",
                source_id,
                org_id,
            )
            if row:
                return row["id"]
            raise ValueError(f"Specified GitHub source {source_id} not found in org {org_id}")

        rows = await conn.fetch(
            "SELECT id, config FROM public.sources WHERE org_id = $1 AND type = 'github'",
            org_id,
        )
        for r in rows:
            cfg = json.loads(r["config"]) if isinstance(r["config"], str) else (r["config"] or {})
            if cfg.get("repo", "").lower() == repo.lower():
                return r["id"]

    if not create_if_missing:
        raise ValueError(f"No GitHub source found for repo '{repo}' in org {org_id}")

    logger.info("Registering new GitHub source for repo '%s' in organization %s...", repo, org_id)
    async with get_connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
            row = await conn.fetchrow(
                """
                INSERT INTO public.sources (
                    org_id, name, type, visibility, config, sync_status
                ) VALUES (
                    $1, $2, 'github', 'public', $3::jsonb, 'ok'
                ) RETURNING id;
                """,
                org_id,
                f"GitHub: {repo}",
                json.dumps({"repo": repo}),
            )
            logger.info("Registered new GitHub source with ID: %s", row["id"])
            return row["id"]


async def resolve_or_create_jira_source(
    org_id: UUID,
    base_url: str,
    project: Optional[str] = None,
    source_id: Optional[UUID] = None,
    create_if_missing: bool = True,
) -> UUID:
    """Find or register a Jira source under org_id."""
    async with worker_transaction_context(org_id) as conn:
        if source_id is not None:
            row = await conn.fetchrow(
                "SELECT id FROM public.sources WHERE id = $1 AND org_id = $2 AND type = 'jira'",
                source_id,
                org_id,
            )
            if row:
                return row["id"]
            raise ValueError(f"Specified Jira source {source_id} not found in org {org_id}")

        rows = await conn.fetch(
            "SELECT id, config FROM public.sources WHERE org_id = $1 AND type = 'jira'",
            org_id,
        )
        for r in rows:
            cfg = json.loads(r["config"]) if isinstance(r["config"], str) else (r["config"] or {})
            cfg_proj = (cfg.get("project") or "").upper()
            target_proj = (project or "").upper()
            if target_proj and cfg_proj == target_proj:
                return r["id"]
            elif not target_proj and cfg.get("base_url", "").rstrip("/") == base_url.rstrip("/"):
                return r["id"]

    if not create_if_missing:
        raise ValueError(f"No Jira source found for project '{project}' in org {org_id}")

    source_name = f"Jira: {project}" if project else f"Jira: {base_url}"
    logger.info("Registering new Jira source '%s' in organization %s...", source_name, org_id)
    config_dict = {"base_url": base_url}
    if project:
        config_dict["project"] = project

    async with get_connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
            row = await conn.fetchrow(
                """
                INSERT INTO public.sources (
                    org_id, name, type, visibility, config, sync_status
                ) VALUES (
                    $1, $2, 'jira', 'public', $3::jsonb, 'ok'
                ) RETURNING id;
                """,
                org_id,
                source_name,
                json.dumps(config_dict),
            )
            logger.info("Registered new Jira source with ID: %s", row["id"])
            return row["id"]


async def resolve_or_create_slack_source(
    org_id: UUID,
    channel_id: str,
    source_id: Optional[UUID] = None,
    create_if_missing: bool = True,
) -> UUID:
    """Find or register a Slack channel source under org_id."""
    async with worker_transaction_context(org_id) as conn:
        if source_id is not None:
            row = await conn.fetchrow(
                "SELECT id FROM public.sources WHERE id = $1 AND org_id = $2 AND type = 'slack'",
                source_id,
                org_id,
            )
            if row:
                return row["id"]
            raise ValueError(f"Specified Slack source {source_id} not found in org {org_id}")

        rows = await conn.fetch(
            "SELECT id, config FROM public.sources WHERE org_id = $1 AND type = 'slack'",
            org_id,
        )
        for r in rows:
            cfg = json.loads(r["config"]) if isinstance(r["config"], str) else (r["config"] or {})
            if cfg.get("channel_id") == channel_id:
                return r["id"]

    if not create_if_missing:
        raise ValueError(f"No Slack source found for channel '{channel_id}' in org {org_id}")

    source_name = f"Slack: {channel_id}"
    logger.info("Registering new Slack source '%s' in organization %s...", source_name, org_id)
    config_dict = {"channel_id": channel_id}

    async with get_connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_org_id', $1, true)", str(org_id))
            row = await conn.fetchrow(
                """
                INSERT INTO public.sources (
                    org_id, name, type, visibility, config, sync_status
                ) VALUES (
                    $1, $2, 'slack', 'public', $3::jsonb, 'ok'
                ) RETURNING id;
                """,
                org_id,
                source_name,
                json.dumps(config_dict),
            )
            logger.info("Registered new Slack source with ID: %s", row["id"])
            return row["id"]


async def run_cli(args: argparse.Namespace) -> int:
    try:
        org_id = UUID(args.org_id)
    except ValueError:
        logger.error("Invalid org-id UUID: %s", args.org_id)
        return 1

    source_id: Optional[UUID] = None
    if args.source_id:
        try:
            source_id = UUID(args.source_id)
        except ValueError:
            logger.error("Invalid source-id UUID: %s", args.source_id)
            return 1

    # Determine source type: Slack, Jira, or GitHub
    is_slack = bool(args.slack_channel or args.slack_token or args.type == "slack")
    is_jira = bool(args.jira_project or args.jira_url or args.jira_token or args.type == "jira")

    if is_slack:
        channel_id = args.slack_channel
        if not channel_id:
            logger.error("Slack channel ID is required (--slack-channel C012345).")
            return 1

        slack_token = args.slack_token or (
            settings.slack_bot_token.get_secret_value() if settings.slack_bot_token else None
        )

        connector = SlackConnector(channel_id=channel_id, token=slack_token)

        logger.info("Validating access to Slack channel '%s'...", channel_id)
        val = await connector.validate()
        if not val.is_valid:
            logger.error("Slack validation failed: %s (Details: %s)", val.message, val.details)
            return 2

        logger.info("Slack validation succeeded: %s", val.message)

        if args.dry_run:
            logger.info("Executing Slack dry-run fetch (limit=%s)...", args.limit)
            res = await connector.fetch(limit=args.limit)
            logger.info("Dry-run fetched %d Slack threads.", len(res.records))
            for r in res.records:
                logger.info("  [%s] %s (links: %d)", r.record_type, r.title, len(r.extracted_links))
            if res.errors:
                logger.warning("Dry-run warnings/errors: %s", res.errors)
            return 0

        resolved_source_id = await resolve_or_create_slack_source(
            org_id=org_id,
            channel_id=channel_id,
            source_id=source_id,
            create_if_missing=True,
        )

    elif is_jira:
        jira_url = (args.jira_url or settings.jira_base_url or "").rstrip("/")
        if not jira_url:
            logger.error("Jira base URL is required. Provide --jira-url or set JIRA_BASE_URL in environment.")
            return 1

        jira_token = args.jira_token or (
            settings.jira_token.get_secret_value() if settings.jira_token else None
        )
        jira_email = args.jira_email or settings.jira_email

        connector = JiraConnector(
            base_url=jira_url,
            email=jira_email,
            token=jira_token,
            project=args.jira_project,
            jql=args.jira_jql,
        )

        logger.info("Validating access to Jira instance '%s'...", jira_url)
        val = await connector.validate()
        if not val.is_valid:
            logger.error("Jira validation failed: %s (Details: %s)", val.message, val.details)
            return 2

        logger.info("Jira validation succeeded: %s", val.message)

        if args.dry_run:
            logger.info("Executing Jira dry-run fetch (limit=%s)...", args.limit)
            res = await connector.fetch(limit=args.limit)
            logger.info("Dry-run fetched %d Jira tickets.", len(res.records))
            for r in res.records:
                logger.info("  [%s] %s (links: %d)", r.record_type, r.title, len(r.extracted_links))
            if res.errors:
                logger.warning("Dry-run warnings/errors: %s", res.errors)
            return 0

        resolved_source_id = await resolve_or_create_jira_source(
            org_id=org_id,
            base_url=jira_url,
            project=args.jira_project,
            source_id=source_id,
            create_if_missing=True,
        )

    else:
        # Default to GitHub
        if not args.repo:
            logger.error("GitHub repository is required (--repo owner/repo) when syncing GitHub.")
            return 1

        repo = args.repo.strip()
        connector = GitHubConnector(repo=repo, token=args.token)

        logger.info("Validating access to repository '%s'...", repo)
        val = await connector.validate()
        if not val.is_valid:
            logger.error("Validation failed: %s (Details: %s)", val.message, val.details)
            return 2

        logger.info("Validation succeeded: %s", val.message)

        if args.dry_run:
            logger.info("Executing dry-run fetch (limit=%s)...", args.limit)
            res = await connector.fetch(limit=args.limit)
            logger.info("Dry-run fetched %d records.", len(res.records))
            for r in res.records:
                logger.info("  [%s] %s (links: %d)", r.record_type, r.title, len(r.extracted_links))
            if res.errors:
                logger.warning("Dry-run warnings/errors: %s", res.errors)
            return 0

        resolved_source_id = await resolve_or_create_github_source(
            org_id=org_id,
            repo=repo,
            source_id=source_id,
            create_if_missing=True,
        )

    logger.info("Starting ingestion into source %s (org: %s)...", resolved_source_id, org_id)
    pipeline = IngestPipeline()
    report = await pipeline.sync_source(
        source_id=resolved_source_id,
        org_id=org_id,
        limit=args.limit,
        connector=connector,
    )

    logger.info(
        "Ingestion finished in %.2fs: status=%s | scanned=%d | created=%d | updated=%d | versions=%d | chunks=%d | links=%d",
        report.duration_seconds,
        report.status,
        report.records_scanned,
        report.records_created,
        report.records_updated,
        report.versions_created,
        report.chunks_created,
        report.links_created,
    )

    if report.errors:
        logger.warning("Pipeline encountered errors:\n" + "\n".join(report.errors))

    return 0 if report.status in ("ok", "partial") else 3


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Handoff Ingestion Pipeline CLI (GitHub, Jira & Slack)")
    parser.add_argument("--type", choices=["github", "jira", "slack"], default=None, help="Connector type")
    parser.add_argument("--org-id", required=True, help="Organization UUID")
    parser.add_argument("--source-id", default=None, help="Existing source UUID (optional)")
    parser.add_argument("--limit", type=int, default=None, help="Maximum records to fetch")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print records without writing to DB")

    # GitHub arguments
    parser.add_argument("--repo", default=None, help="GitHub repository in owner/repo format")
    parser.add_argument("--token", default=None, help="GitHub personal access token override")

    # Jira arguments
    parser.add_argument("--jira-url", default=None, help="Jira Cloud base URL (e.g. https://company.atlassian.net)")
    parser.add_argument("--jira-email", default=None, help="Jira Cloud account email")
    parser.add_argument("--jira-token", default=None, help="Jira Cloud API token")
    parser.add_argument("--jira-project", default=None, help="Jira project key (e.g. PROJ, ENG)")
    parser.add_argument("--jira-jql", default=None, help="Custom JQL filter expression")

    # Slack arguments
    parser.add_argument("--slack-channel", default=None, help="Slack channel ID (e.g. C0123456789)")
    parser.add_argument("--slack-token", default=None, help="Slack bot token override (xoxb-...)")

    parsed_args = parser.parse_args()

    try:
        return await run_cli(parsed_args)
    finally:
        await close_pool()


def main() -> None:
    sys.exit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
