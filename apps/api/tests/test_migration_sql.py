"""
Automated unit tests validating the integrity and security design of 001_init.sql.

NOTE: These tests perform static analysis and invariant verification on the SQL
migration script. Runtime behavior and PostgreSQL 17 execution semantics have not
been integration-tested against a live PostgreSQL instance per task restrictions.
"""

from pathlib import Path
import re
import pytest

_MIGRATION_PATH = Path(__file__).resolve().parent.parent.parent.parent / "db" / "migrations" / "001_init.sql"


@pytest.fixture(scope="module")
def migration_sql() -> str:
    assert _MIGRATION_PATH.exists(), f"Migration file missing at {_MIGRATION_PATH}"
    return _MIGRATION_PATH.read_text(encoding="utf-8")


def test_table_inventory(migration_sql: str) -> None:
    expected_tables = {
        "organizations",
        "memberships",
        "sources",
        "source_access_grants",
        "records",
        "record_versions",
        "chunks",
        "record_links",
        "knowledge_notes",
        "knowledge_gaps",
        "handoffs",
        "handoff_items",
        "answers",
        "claims",
    }
    created_tables = set(re.findall(r"CREATE\s+TABLE\s+public\.([a-z_]+)", migration_sql, re.IGNORECASE))
    assert expected_tables == created_tables, f"Mismatch in tables: {expected_tables ^ created_tables}"
    assert len(created_tables) == 14


def test_vector_extension_and_dimension(migration_sql: str) -> None:
    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration_sql
    assert "WITH SCHEMA extensions" in migration_sql
    assert "vector(384)" in migration_sql
    assert "CREATE INDEX idx_chunks_embedding_hnsw" in migration_sql


def test_role_definitions_safe(migration_sql: str) -> None:
    assert "CREATE ROLE app_runtime WITH LOGIN NOSUPERUSER NOBYPASSRLS" in migration_sql
    assert "CREATE ROLE app_sync WITH LOGIN NOSUPERUSER NOBYPASSRLS" in migration_sql
    # Ensure no PASSWORD clause is in CREATE ROLE statement
    assert not re.search(r"CREATE\s+ROLE\s+\w+\s+[^;]*\bPASSWORD\b", migration_sql, re.IGNORECASE)


def test_least_privilege_grants_separation(migration_sql: str) -> None:
    # app_runtime MUST NOT have DELETE on answers, claims, records, record_versions, chunks, organizations
    forbidden_runtime_deletes = ["answers", "claims", "records", "record_versions", "chunks", "organizations"]
    for table in forbidden_runtime_deletes:
        pattern = rf"GRANT\s+[^;]*\bDELETE\b[^;]*\bON\s+(?:TABLE\s+)?public\.{table}\s+TO\s+app_runtime\b"
        assert not re.search(pattern, migration_sql, re.IGNORECASE), f"app_runtime improperly granted DELETE on {table}"

    # app_runtime MUST NOT have INSERT on records, record_versions, chunks (ingestion tables)
    forbidden_runtime_inserts = ["records", "record_versions", "chunks"]
    for table in forbidden_runtime_inserts:
        pattern = rf"GRANT\s+[^;]*\bINSERT\b[^;]*\bON\s+(?:TABLE\s+)?public\.{table}\s+TO\s+app_runtime\b"
        assert not re.search(pattern, migration_sql, re.IGNORECASE), f"app_runtime improperly granted INSERT on {table}"

    # app_sync MUST NOT have any access to user content, answers, claims, handoffs, notes, grants
    forbidden_sync_tables = ["answers", "claims", "handoffs", "handoff_items", "knowledge_notes", "source_access_grants", "knowledge_gaps"]
    for table in forbidden_sync_tables:
        pattern = rf"GRANT\s+[^;]*\bON\s+(?:TABLE\s+)?public\.{table}\s+TO\s+app_sync\b"
        assert not re.search(pattern, migration_sql, re.IGNORECASE), f"app_sync improperly granted permissions on {table}"


def test_rls_enabled_on_all_tables(migration_sql: str) -> None:
    expected_tables = [
        "organizations", "memberships", "sources", "source_access_grants",
        "records", "record_versions", "chunks", "record_links",
        "knowledge_notes", "knowledge_gaps", "handoffs", "handoff_items",
        "answers", "claims"
    ]
    for table in expected_tables:
        pattern = rf"ALTER\s+TABLE\s+public\.{table}\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY;"
        assert re.search(pattern, migration_sql, re.IGNORECASE), f"RLS not enabled on {table}"


def test_rls_policies_comprehensive(migration_sql: str) -> None:
    # Verify explicit action policies exist for user workflows
    assert "CREATE POLICY org_select_policy" in migration_sql
    assert "CREATE POLICY membership_insert_policy" in migration_sql
    assert "CREATE POLICY sources_admin_insert_policy" in migration_sql
    assert "CREATE POLICY sources_user_select_policy" in migration_sql
    assert "CREATE POLICY sources_worker_select_policy" in migration_sql
    assert "CREATE POLICY notes_insert_policy" in migration_sql
    assert "CREATE POLICY notes_update_policy" in migration_sql
    assert "CREATE POLICY handoffs_insert_policy" in migration_sql
    assert "CREATE POLICY handoffs_update_policy" in migration_sql
    assert "CREATE POLICY answers_insert_policy" in migration_sql
    assert "CREATE POLICY claims_insert_policy" in migration_sql
    assert "CREATE POLICY links_user_select_policy" in migration_sql
    assert "CREATE POLICY links_worker_select_policy" in migration_sql


def test_security_definer_helpers(migration_sql: str) -> None:
    helpers = ["current_app_user", "current_app_org", "is_org_admin", "user_can_access_source", "get_record_source_id"]
    for helper in helpers:
        # Check ownership explicitly set to postgres
        assert f"ALTER FUNCTION public.{helper}" in migration_sql
        assert f"OWNER TO postgres" in migration_sql
        # Check search_path fixed
        assert "SET search_path = public, pg_temp" in migration_sql
        # Check execute revoked from public and granted to runtime roles
        assert f"REVOKE ALL ON FUNCTION public.{helper}" in migration_sql
        assert f"GRANT EXECUTE ON FUNCTION public.{helper}" in migration_sql

    # Trigger functions ownership and search_path hardening
    trigger_functions = [
        "handle_new_record_version",
        "enforce_record_version_immutability",
        "validate_claim_verbatim_quote",
    ]
    for fn in trigger_functions:
        assert f"ALTER FUNCTION public.{fn}() OWNER TO postgres;" in migration_sql
        assert f"REVOKE ALL ON FUNCTION public.{fn}() FROM PUBLIC;" in migration_sql


def test_evidence_immutability_and_version_consistency(migration_sql: str) -> None:
    # Trigger functions exist
    assert "public.handle_new_record_version()" in migration_sql
    assert "public.enforce_record_version_immutability()" in migration_sql
    assert "public.validate_claim_verbatim_quote()" in migration_sql

    # Concurrency serialization lock on parent record
    assert "FOR NO KEY UPDATE" in migration_sql
    
    # Partial unique index for single latest version
    assert "uq_record_versions_single_latest" in migration_sql
    assert "WHERE is_latest = true" in migration_sql

    # Evidence retention: RESTRICT on delete for records and versions
    assert "REFERENCES public.sources(id, org_id) ON DELETE RESTRICT" in migration_sql
    assert "REFERENCES public.records(id, source_id, org_id) ON DELETE RESTRICT" in migration_sql
    assert "REFERENCES public.record_versions(id, record_id, org_id) ON DELETE RESTRICT" in migration_sql


def test_composite_foreign_keys_and_attribution(migration_sql: str) -> None:
    # Verify chunks references record_version with full composite key
    assert re.search(
        r"FOREIGN\s+KEY\s*\(record_version_id,\s*record_id,\s*source_id,\s*org_id\)\s*REFERENCES\s+public\.record_versions",
        migration_sql,
        re.IGNORECASE,
    )
    # Verify user attribution checks memberships composite (not just raw auth.users)
    assert re.search(
        r"FOREIGN\s+KEY\s*\(org_id,\s*author_user_id\)\s*REFERENCES\s+public\.memberships",
        migration_sql,
        re.IGNORECASE,
    )
    assert re.search(
        r"FOREIGN\s+KEY\s*\(org_id,\s*departing_user_id\)\s*REFERENCES\s+public\.memberships",
        migration_sql,
        re.IGNORECASE,
    )


def test_schema_usage_and_role_isolation(migration_sql: str) -> None:
    # Ensure USAGE granted on public and extensions to runtime roles
    assert "GRANT USAGE ON SCHEMA public TO app_runtime, app_sync;" in migration_sql
    assert "GRANT USAGE ON SCHEMA extensions TO app_runtime, app_sync;" in migration_sql
    # Ensure no role escalation membership is granted to postgres
    assert not re.search(r"GRANT\s+app_runtime\b[^;]*\bTO\s+postgres\b", migration_sql, re.IGNORECASE)
    assert not re.search(r"GRANT\s+app_sync\b[^;]*\bTO\s+postgres\b", migration_sql, re.IGNORECASE)
