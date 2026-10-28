-- ============================================================================
-- 001_init.sql: Institutional Memory Agent Initial Schema Migration
-- Target Engine: PostgreSQL 17+ (Supabase)
-- 
-- Architecture Principles:
-- 1. Strict multi-tenant isolation by organization (org_id).
-- 2. Composite foreign keys enforce tenant consistency across child relationships.
-- 3. Evidence history is immutable: record_versions is strictly append-only.
-- 4. Claims link to exact record_versions; verified quotes must be verbatim substrings.
-- 5. Row-Level Security (RLS) is enabled on all tables with explicit action policies.
-- 6. Role separation: postgres (DDL owner), app_runtime (API), app_sync (ingest worker).
-- 7. Audit preservation: records/versions/claims cannot be deleted via cascade.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. EXTENSIONS
-- ----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- ----------------------------------------------------------------------------
-- 2. ROLE DEFINITIONS (Least Privilege, Direct Authentication, No Passwords Embedded)
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_runtime') THEN
        CREATE ROLE app_runtime WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    ELSE
        ALTER ROLE app_runtime WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_sync') THEN
        CREATE ROLE app_sync WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    ELSE
        ALTER ROLE app_sync WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app_runtime, app_sync;
GRANT USAGE ON SCHEMA extensions TO app_runtime, app_sync;

-- ----------------------------------------------------------------------------
-- 3. TABLE INVENTORY & CONSTRAINTS
-- ----------------------------------------------------------------------------

-- Table 1: organizations (Tenant Root)
CREATE TABLE public.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Table 2: memberships (User-Tenant Association with Role)
CREATE TABLE public.memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_memberships_org_user UNIQUE (org_id, user_id)
);

-- Table 3: sources
-- Secret Storage: encrypted_credentials stores binary AES-256-GCM payload:
-- [ Version (1B) || IV/Nonce (12B) || Auth Tag (16B) || Ciphertext ]
-- AAD is bound to: org_id || ':' || source_id
CREATE TABLE public.sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('github', 'jira', 'slack', 'meeting')),
    visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'restricted')),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    encrypted_credentials BYTEA,
    sync_status TEXT NOT NULL DEFAULT 'ok' CHECK (sync_status IN ('ok', 'partial', 'failed', 'running')),
    sync_cursor JSONB DEFAULT '{}'::jsonb,
    last_synced_at TIMESTAMPTZ,
    error_message TEXT,
    is_archived BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_sources_id_org UNIQUE (id, org_id)
);

-- Table 4: source_access_grants (Admin-granted access to restricted sources)
CREATE TABLE public.source_access_grants (
    source_id UUID NOT NULL,
    user_id UUID NOT NULL,
    org_id UUID NOT NULL,
    granted_by_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, user_id),
    CONSTRAINT fk_grants_source FOREIGN KEY (source_id, org_id) 
        REFERENCES public.sources(id, org_id) ON DELETE CASCADE,
    CONSTRAINT fk_grants_user FOREIGN KEY (org_id, user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE CASCADE,
    CONSTRAINT fk_grants_grantor FOREIGN KEY (org_id, granted_by_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (granted_by_user_id)
);

-- Table 5: records (Canonical registry of upstream entities)
-- ON DELETE RESTRICT prevents deleting sources that contain historical records.
CREATE TABLE public.records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    source_id UUID NOT NULL,
    external_id TEXT NOT NULL,
    record_type TEXT NOT NULL CHECK (record_type IN ('commit', 'pull_request', 'review_comment', 'issue', 'ticket', 'slack_thread', 'meeting')),
    title TEXT NOT NULL,
    url TEXT,
    author_name TEXT,
    author_email TEXT,
    is_deleted_upstream BOOLEAN NOT NULL DEFAULT false,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_records_source FOREIGN KEY (source_id, org_id) 
        REFERENCES public.sources(id, org_id) ON DELETE RESTRICT,
    CONSTRAINT uq_records_source_external UNIQUE (source_id, external_id),
    CONSTRAINT uq_records_id_org UNIQUE (id, org_id),
    CONSTRAINT uq_records_id_source_org UNIQUE (id, source_id, org_id)
);

-- Table 6: record_versions (Append-only immutable evidence snapshots)
-- ON DELETE RESTRICT prevents deleting records that have historical versions.
CREATE TABLE public.record_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_id UUID NOT NULL,
    source_id UUID NOT NULL,
    org_id UUID NOT NULL,
    version_index INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_created_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_latest BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT fk_versions_record FOREIGN KEY (record_id, source_id, org_id) 
        REFERENCES public.records(id, source_id, org_id) ON DELETE RESTRICT,
    CONSTRAINT uq_versions_record_version UNIQUE (record_id, version_index),
    CONSTRAINT uq_versions_id_org UNIQUE (id, org_id),
    CONSTRAINT uq_versions_composite UNIQUE (id, record_id, org_id),
    CONSTRAINT uq_versions_full UNIQUE (id, record_id, source_id, org_id)
);

-- Partial index guaranteeing at most ONE latest version per record
CREATE UNIQUE INDEX uq_record_versions_single_latest 
    ON public.record_versions(record_id) 
    WHERE is_latest = true;

-- Table 7: chunks (Searchable vector embeddings of immutable record versions)
CREATE TABLE public.chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    record_version_id UUID NOT NULL,
    record_id UUID NOT NULL,
    source_id UUID NOT NULL,
    org_id UUID NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding vector(384),
    token_count INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_chunks_version FOREIGN KEY (record_version_id, record_id, source_id, org_id) 
        REFERENCES public.record_versions(id, record_id, source_id, org_id) ON DELETE CASCADE,
    CONSTRAINT uq_chunks_version_index UNIQUE (record_version_id, chunk_index)
);

-- Table 8: record_links (Explicit and inferred relationships)
CREATE TABLE public.record_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    from_record_id UUID NOT NULL,
    to_record_id UUID NOT NULL,
    link_type TEXT NOT NULL CHECK (link_type IN ('explicit', 'human_confirmed', 'inferred')),
    provenance TEXT NOT NULL CHECK (provenance IN ('commit_message', 'jira_link', 'slack_reference', 'pr_description', 'user_action')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_links_from FOREIGN KEY (from_record_id, org_id) 
        REFERENCES public.records(id, org_id) ON DELETE CASCADE,
    CONSTRAINT fk_links_to FOREIGN KEY (to_record_id, org_id) 
        REFERENCES public.records(id, org_id) ON DELETE CASCADE,
    CONSTRAINT uq_links_pair UNIQUE (from_record_id, to_record_id, link_type),
    CONSTRAINT chk_links_no_self CHECK (from_record_id <> to_record_id)
);

-- Table 9: knowledge_notes (Human-attributed bridge knowledge)
CREATE TABLE public.knowledge_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    author_user_id UUID,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'personal' CHECK (status IN ('personal', 'reviewed', 'archived')),
    reviewed_by_user_id UUID,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_notes_author FOREIGN KEY (org_id, author_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (author_user_id),
    CONSTRAINT fk_notes_reviewer FOREIGN KEY (org_id, reviewed_by_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (reviewed_by_user_id),
    CONSTRAINT uq_notes_id_org UNIQUE (id, org_id)
);

-- Table 10: knowledge_gaps (Identified rationale gaps from abstentions)
CREATE TABLE public.knowledge_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    context TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'dismissed')),
    proposed_to_user_id UUID,
    answered_note_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_gaps_proposed_to FOREIGN KEY (org_id, proposed_to_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (proposed_to_user_id),
    CONSTRAINT fk_gaps_answered_note FOREIGN KEY (answered_note_id, org_id) 
        REFERENCES public.knowledge_notes(id, org_id) ON DELETE SET NULL (answered_note_id),
    CONSTRAINT uq_gaps_id_org UNIQUE (id, org_id)
);

-- Table 11: handoffs (Structured handoff containers)
CREATE TABLE public.handoffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('person', 'service')),
    subject_identifier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'confirmed', 'acknowledged', 'archived')),
    departing_user_id UUID,
    recipient_user_id UUID,
    created_by_user_id UUID,
    summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    confirmed_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    CONSTRAINT fk_handoffs_departing FOREIGN KEY (org_id, departing_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (departing_user_id),
    CONSTRAINT fk_handoffs_recipient FOREIGN KEY (org_id, recipient_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (recipient_user_id),
    CONSTRAINT fk_handoffs_creator FOREIGN KEY (org_id, created_by_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (created_by_user_id),
    CONSTRAINT uq_handoffs_id_org UNIQUE (id, org_id)
);

-- Table 12: handoff_items
CREATE TABLE public.handoff_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    handoff_id UUID NOT NULL,
    org_id UUID NOT NULL,
    record_id UUID,
    gap_id UUID,
    note_id UUID,
    title TEXT NOT NULL,
    description TEXT,
    item_status TEXT NOT NULL CHECK (item_status IN ('verified', 'inferred', 'unresolved', 'outdated')),
    CONSTRAINT fk_items_handoff FOREIGN KEY (handoff_id, org_id) 
        REFERENCES public.handoffs(id, org_id) ON DELETE CASCADE,
    CONSTRAINT fk_items_record FOREIGN KEY (record_id, org_id) 
        REFERENCES public.records(id, org_id) ON DELETE SET NULL (record_id),
    CONSTRAINT fk_items_gap FOREIGN KEY (gap_id, org_id) 
        REFERENCES public.knowledge_gaps(id, org_id) ON DELETE SET NULL (gap_id),
    CONSTRAINT fk_items_note FOREIGN KEY (note_id, org_id) 
        REFERENCES public.knowledge_notes(id, org_id) ON DELETE SET NULL (note_id)
);

-- Table 13: answers (Audited investigation answers and traces)
CREATE TABLE public.answers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    evidence_level TEXT NOT NULL CHECK (evidence_level IN ('documented', 'inferred', 'unknown')),
    evidence_reason TEXT NOT NULL,
    is_abstention BOOLEAN NOT NULL DEFAULT false,
    staleness_warning TEXT,
    investigation_trace JSONB NOT NULL DEFAULT '[]'::jsonb,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    feedback_rating INTEGER CHECK (feedback_rating IN (1, -1)),
    feedback_notes TEXT,
    created_by_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_answers_creator FOREIGN KEY (org_id, created_by_user_id) 
        REFERENCES public.memberships(org_id, user_id) ON DELETE SET NULL (created_by_user_id),
    CONSTRAINT chk_answers_abstention CHECK ((is_abstention = false) OR (is_abstention = true AND evidence_level = 'unknown')),
    CONSTRAINT uq_answers_id_org UNIQUE (id, org_id)
);

-- Table 14: claims (Atomic claims referencing exact historical record versions)
-- ON DELETE RESTRICT prevents deleting record_versions cited by historical claims.
CREATE TABLE public.claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    answer_id UUID NOT NULL,
    record_version_id UUID NOT NULL,
    record_id UUID NOT NULL,
    org_id UUID NOT NULL,
    claim_text TEXT NOT NULL,
    exact_quote TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN ('verified', 'unsupported', 'dropped')),
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('documented', 'inferred', 'unknown')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_claims_answer FOREIGN KEY (answer_id, org_id) 
        REFERENCES public.answers(id, org_id) ON DELETE CASCADE,
    CONSTRAINT fk_claims_version FOREIGN KEY (record_version_id, record_id, org_id) 
        REFERENCES public.record_versions(id, record_id, org_id) ON DELETE RESTRICT
);

-- ----------------------------------------------------------------------------
-- 4. HARDENED HELPER FUNCTIONS (Trusted-Backend Context & Permissions)
--
-- SECURITY ADVISORY ON TRUSTED-BACKEND CONTEXT:
-- Setting session settings ('app.current_user_id', 'app.current_org_id') does NOT
-- cryptographically authenticate the caller to PostgreSQL. It is Trusted-Backend
-- Context provided by FastAPI after validating the Supabase Auth JWT.
--
-- What it protects against:
-- - Accidental developer omissions of WHERE org_id = :org_id in complex queries.
-- - Indirect data leaks in graph link traversals and pgvector similarity searches.
--
-- What it does NOT protect against:
-- - A malicious caller who achieves arbitrary SQL execution under app_runtime or app_sync.
-- - A fully compromised FastAPI backend holding database role credentials.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.current_app_user() 
RETURNS uuid 
LANGUAGE sql 
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION public.current_app_org() 
RETURNS uuid 
LANGUAGE sql 
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT NULLIF(current_setting('app.current_org_id', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION public.is_org_admin(check_org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.memberships
    WHERE org_id = check_org_id
      AND user_id = public.current_app_user()
      AND role = 'admin'
  );
$$;

CREATE OR REPLACE FUNCTION public.user_can_access_source(lookup_source_id uuid, lookup_org_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 
    FROM public.sources s
    JOIN public.memberships m 
      ON m.org_id = s.org_id 
     AND m.user_id = public.current_app_user()
    WHERE s.id = lookup_source_id
      AND s.org_id = lookup_org_id
      AND s.org_id = public.current_app_org()
      AND (
        m.role = 'admin'
        OR s.visibility = 'public'
        OR EXISTS (
          SELECT 1 FROM public.source_access_grants sag
          WHERE sag.source_id = s.id
            AND sag.user_id = public.current_app_user()
            AND sag.org_id = lookup_org_id
        )
      )
  );
$$;

-- Helper to safely resolve a record's source_id without triggering nested RLS on records
CREATE OR REPLACE FUNCTION public.get_record_source_id(lookup_record_id uuid, lookup_org_id uuid)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT source_id 
  FROM public.records 
  WHERE id = lookup_record_id 
    AND org_id = lookup_org_id;
$$;

-- Ownership & execution security
ALTER FUNCTION public.current_app_user() OWNER TO postgres;
ALTER FUNCTION public.current_app_org() OWNER TO postgres;
ALTER FUNCTION public.is_org_admin(uuid) OWNER TO postgres;
ALTER FUNCTION public.user_can_access_source(uuid, uuid) OWNER TO postgres;
ALTER FUNCTION public.get_record_source_id(uuid, uuid) OWNER TO postgres;

REVOKE ALL ON FUNCTION public.current_app_user() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.current_app_org() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.is_org_admin(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.user_can_access_source(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_record_source_id(uuid, uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.current_app_user() TO app_runtime, app_sync;
GRANT EXECUTE ON FUNCTION public.current_app_org() TO app_runtime, app_sync;
GRANT EXECUTE ON FUNCTION public.is_org_admin(uuid) TO app_runtime, app_sync;
GRANT EXECUTE ON FUNCTION public.user_can_access_source(uuid, uuid) TO app_runtime, app_sync;
GRANT EXECUTE ON FUNCTION public.get_record_source_id(uuid, uuid) TO app_runtime, app_sync;

-- ----------------------------------------------------------------------------
-- 5. EVIDENCE IMMUTABILITY & VERBATIM QUOTE VALIDATION TRIGGERS
-- ----------------------------------------------------------------------------

-- Safely retire previous latest version before inserting a new version
CREATE OR REPLACE FUNCTION public.handle_new_record_version()
RETURNS trigger 
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.is_latest = true THEN
        -- Serialize concurrent version appends on the parent record to prevent race conditions
        PERFORM 1 FROM public.records 
        WHERE id = NEW.record_id AND org_id = NEW.org_id 
        FOR NO KEY UPDATE;

        UPDATE public.record_versions
        SET is_latest = false
        WHERE record_id = NEW.record_id
          AND org_id = NEW.org_id
          AND is_latest = true
          AND id <> NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_retire_previous_record_version
    BEFORE INSERT ON public.record_versions
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_record_version();

-- Enforce strict immutability of record_versions content and metadata
CREATE OR REPLACE FUNCTION public.enforce_record_version_immutability()
RETURNS trigger 
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- Allow ONLY retiring the is_latest flag; strictly forbid altering content or metadata
        IF OLD.is_latest = true AND NEW.is_latest = false AND
           NEW.id = OLD.id AND
           NEW.record_id = OLD.record_id AND
           NEW.source_id = OLD.source_id AND
           NEW.org_id = OLD.org_id AND
           NEW.version_index = OLD.version_index AND
           NEW.content = OLD.content AND
           NEW.content_hash = OLD.content_hash AND
           NEW.source_created_at = OLD.source_created_at AND
           NEW.source_updated_at = OLD.source_updated_at AND
           NEW.synced_at = OLD.synced_at AND
           NEW.metadata = OLD.metadata THEN
            RETURN NEW;
        ELSE
            RAISE EXCEPTION 'record_versions content and metadata are immutable and cannot be modified';
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'record_versions rows are immutable historical snapshots and cannot be deleted';
    END IF;
END;
$$;

CREATE TRIGGER trg_protect_record_versions
    BEFORE UPDATE OR DELETE ON public.record_versions
    FOR EACH ROW EXECUTE FUNCTION public.enforce_record_version_immutability();

-- Validate that verified claims contain verbatim substrings of the exact historical version
CREATE OR REPLACE FUNCTION public.validate_claim_verbatim_quote()
RETURNS trigger 
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_content text;
BEGIN
    IF NEW.verification_status = 'verified' THEN
        SELECT content INTO v_content
        FROM public.record_versions
        WHERE id = NEW.record_version_id
          AND record_id = NEW.record_id
          AND org_id = NEW.org_id;

        IF v_content IS NULL THEN
            RAISE EXCEPTION 'Claim references non-existent or cross-tenant record version %', NEW.record_version_id;
        END IF;

        IF length(trim(NEW.exact_quote)) < 10 THEN
            RAISE EXCEPTION 'Claim quote too short (minimum 10 characters required)';
        END IF;

        IF strpos(v_content, NEW.exact_quote) = 0 THEN
            RAISE EXCEPTION 'Claim quote verification failed: exact quote is not a verbatim substring of referenced record version %', NEW.record_version_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_claim_quote
    BEFORE INSERT OR UPDATE ON public.claims
    FOR EACH ROW EXECUTE FUNCTION public.validate_claim_verbatim_quote();

-- Ownership and access hardening for trigger functions
ALTER FUNCTION public.handle_new_record_version() OWNER TO postgres;
ALTER FUNCTION public.enforce_record_version_immutability() OWNER TO postgres;
ALTER FUNCTION public.validate_claim_verbatim_quote() OWNER TO postgres;

REVOKE ALL ON FUNCTION public.handle_new_record_version() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.enforce_record_version_immutability() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.validate_claim_verbatim_quote() FROM PUBLIC;

-- ----------------------------------------------------------------------------
-- 6. ROW-LEVEL SECURITY (RLS) POLICIES (Explicit Actions Per Table)
-- ----------------------------------------------------------------------------

ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_access_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.record_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.record_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.knowledge_gaps ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.handoff_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.answers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.claims ENABLE ROW LEVEL SECURITY;

-- 1. organizations
CREATE POLICY org_select_policy ON public.organizations
    FOR SELECT TO app_runtime, app_sync
    USING (id = public.current_app_org());

CREATE POLICY org_update_policy ON public.organizations
    FOR UPDATE TO app_runtime
    USING (id = public.current_app_org() AND public.is_org_admin(id))
    WITH CHECK (id = public.current_app_org() AND public.is_org_admin(id));

-- 2. memberships (Direct comparison, recursion-free)
CREATE POLICY membership_select_policy ON public.memberships
    FOR SELECT TO app_runtime, app_sync
    USING (
        org_id = public.current_app_org() 
        AND (user_id = public.current_app_user() OR public.is_org_admin(org_id))
    );

CREATE POLICY membership_insert_policy ON public.memberships
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = public.current_app_org() AND public.is_org_admin(org_id));

CREATE POLICY membership_update_policy ON public.memberships
    FOR UPDATE TO app_runtime
    USING (org_id = public.current_app_org() AND public.is_org_admin(org_id))
    WITH CHECK (org_id = public.current_app_org() AND public.is_org_admin(org_id));

CREATE POLICY membership_delete_policy ON public.memberships
    FOR DELETE TO app_runtime
    USING (
        org_id = public.current_app_org() 
        AND (public.is_org_admin(org_id) OR user_id = public.current_app_user())
    );

-- 3. sources
CREATE POLICY sources_user_select_policy ON public.sources
    FOR SELECT TO app_runtime
    USING (public.user_can_access_source(id, org_id));

CREATE POLICY sources_worker_select_policy ON public.sources
    FOR SELECT TO app_sync
    USING (org_id = public.current_app_org());

CREATE POLICY sources_admin_insert_policy ON public.sources
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = public.current_app_org() AND public.is_org_admin(org_id));

CREATE POLICY sources_admin_update_policy ON public.sources
    FOR UPDATE TO app_runtime
    USING (org_id = public.current_app_org() AND public.is_org_admin(org_id))
    WITH CHECK (org_id = public.current_app_org() AND public.is_org_admin(org_id));

CREATE POLICY sources_worker_update_policy ON public.sources
    FOR UPDATE TO app_sync
    USING (org_id = public.current_app_org())
    WITH CHECK (org_id = public.current_app_org());

-- 4. source_access_grants
CREATE POLICY grants_select_policy ON public.source_access_grants
    FOR SELECT TO app_runtime
    USING (
        org_id = public.current_app_org()
        AND (user_id = public.current_app_user() OR public.is_org_admin(org_id))
    );

CREATE POLICY grants_admin_insert_policy ON public.source_access_grants
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = public.current_app_org() AND public.is_org_admin(org_id));

CREATE POLICY grants_admin_delete_policy ON public.source_access_grants
    FOR DELETE TO app_runtime
    USING (org_id = public.current_app_org() AND public.is_org_admin(org_id));

-- 5. records
CREATE POLICY records_user_select_policy ON public.records
    FOR SELECT TO app_runtime
    USING (public.user_can_access_source(source_id, org_id));

CREATE POLICY records_worker_select_policy ON public.records
    FOR SELECT TO app_sync
    USING (org_id = public.current_app_org());

CREATE POLICY records_worker_insert_policy ON public.records
    FOR INSERT TO app_sync
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY records_worker_update_policy ON public.records
    FOR UPDATE TO app_sync
    USING (org_id = public.current_app_org())
    WITH CHECK (org_id = public.current_app_org());

-- 6. record_versions
CREATE POLICY versions_user_select_policy ON public.record_versions
    FOR SELECT TO app_runtime
    USING (public.user_can_access_source(source_id, org_id));

CREATE POLICY versions_worker_select_policy ON public.record_versions
    FOR SELECT TO app_sync
    USING (org_id = public.current_app_org());

CREATE POLICY versions_worker_insert_policy ON public.record_versions
    FOR INSERT TO app_sync
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY versions_worker_update_policy ON public.record_versions
    FOR UPDATE TO app_sync
    USING (org_id = public.current_app_org())
    WITH CHECK (org_id = public.current_app_org());

-- 7. chunks
CREATE POLICY chunks_user_select_policy ON public.chunks
    FOR SELECT TO app_runtime
    USING (public.user_can_access_source(source_id, org_id));

CREATE POLICY chunks_worker_select_policy ON public.chunks
    FOR SELECT TO app_sync
    USING (org_id = public.current_app_org());

CREATE POLICY chunks_worker_insert_policy ON public.chunks
    FOR INSERT TO app_sync
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY chunks_worker_delete_policy ON public.chunks
    FOR DELETE TO app_sync
    USING (org_id = public.current_app_org());

-- 8. record_links
-- Uses get_record_source_id helper to verify both endpoints without nested RLS failure
CREATE POLICY links_user_select_policy ON public.record_links
    FOR SELECT TO app_runtime
    USING (
        org_id = public.current_app_org()
        AND public.user_can_access_source(public.get_record_source_id(from_record_id, org_id), org_id)
        AND public.user_can_access_source(public.get_record_source_id(to_record_id, org_id), org_id)
    );

CREATE POLICY links_worker_select_policy ON public.record_links
    FOR SELECT TO app_sync
    USING (org_id = public.current_app_org());

CREATE POLICY links_worker_insert_policy ON public.record_links
    FOR INSERT TO app_sync
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY links_worker_delete_policy ON public.record_links
    FOR DELETE TO app_sync
    USING (org_id = public.current_app_org());

CREATE POLICY links_user_insert_policy ON public.record_links
    FOR INSERT TO app_runtime
    WITH CHECK (
        org_id = public.current_app_org()
        AND link_type = 'human_confirmed'
        AND public.user_can_access_source(public.get_record_source_id(from_record_id, org_id), org_id)
        AND public.user_can_access_source(public.get_record_source_id(to_record_id, org_id), org_id)
    );

CREATE POLICY links_user_delete_policy ON public.record_links
    FOR DELETE TO app_runtime
    USING (
        org_id = public.current_app_org()
        AND (public.is_org_admin(org_id) OR link_type = 'human_confirmed')
    );

-- 9. knowledge_notes
CREATE POLICY notes_select_policy ON public.knowledge_notes
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY notes_insert_policy ON public.knowledge_notes
    FOR INSERT TO app_runtime
    WITH CHECK (
        org_id = public.current_app_org() 
        AND author_user_id = public.current_app_user()
    );

CREATE POLICY notes_update_policy ON public.knowledge_notes
    FOR UPDATE TO app_runtime
    USING (
        org_id = public.current_app_org() 
        AND (
            (author_user_id = public.current_app_user() AND status = 'personal')
            OR public.is_org_admin(org_id)
        )
    )
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY notes_delete_policy ON public.knowledge_notes
    FOR DELETE TO app_runtime
    USING (
        org_id = public.current_app_org() 
        AND author_user_id = public.current_app_user() 
        AND status = 'personal'
    );

-- 10. knowledge_gaps
CREATE POLICY gaps_select_policy ON public.knowledge_gaps
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY gaps_insert_policy ON public.knowledge_gaps
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY gaps_update_policy ON public.knowledge_gaps
    FOR UPDATE TO app_runtime
    USING (org_id = public.current_app_org())
    WITH CHECK (org_id = public.current_app_org());

-- 11. handoffs
CREATE POLICY handoffs_select_policy ON public.handoffs
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY handoffs_insert_policy ON public.handoffs
    FOR INSERT TO app_runtime
    WITH CHECK (
        org_id = public.current_app_org() 
        AND created_by_user_id = public.current_app_user()
    );

CREATE POLICY handoffs_update_policy ON public.handoffs
    FOR UPDATE TO app_runtime
    USING (
        org_id = public.current_app_org() 
        AND (
            created_by_user_id = public.current_app_user() 
            OR recipient_user_id = public.current_app_user() 
            OR public.is_org_admin(org_id)
        )
    )
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY handoffs_delete_policy ON public.handoffs
    FOR DELETE TO app_runtime
    USING (
        org_id = public.current_app_org() 
        AND created_by_user_id = public.current_app_user() 
        AND status = 'draft'
    );

-- 12. handoff_items
CREATE POLICY handoff_items_select_policy ON public.handoff_items
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY handoff_items_insert_policy ON public.handoff_items
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY handoff_items_update_policy ON public.handoff_items
    FOR UPDATE TO app_runtime
    USING (org_id = public.current_app_org())
    WITH CHECK (org_id = public.current_app_org());

CREATE POLICY handoff_items_delete_policy ON public.handoff_items
    FOR DELETE TO app_runtime
    USING (org_id = public.current_app_org());

-- 13. answers
CREATE POLICY answers_select_policy ON public.answers
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY answers_insert_policy ON public.answers
    FOR INSERT TO app_runtime
    WITH CHECK (
        org_id = public.current_app_org() 
        AND created_by_user_id = public.current_app_user()
    );

CREATE POLICY answers_update_policy ON public.answers
    FOR UPDATE TO app_runtime
    USING (
        org_id = public.current_app_org() 
        AND created_by_user_id = public.current_app_user()
    )
    WITH CHECK (
        org_id = public.current_app_org() 
        AND created_by_user_id = public.current_app_user()
    );

-- 14. claims
CREATE POLICY claims_select_policy ON public.claims
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY claims_insert_policy ON public.claims
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = public.current_app_org());

-- ----------------------------------------------------------------------------
-- 7. PERFORMANCE, TENANT & VECTOR INDEXES
-- ----------------------------------------------------------------------------

-- Tenant & Membership indexes
CREATE INDEX idx_memberships_user ON public.memberships(user_id);
CREATE INDEX idx_memberships_org ON public.memberships(org_id);

-- Sources & Grants
CREATE INDEX idx_sources_org_status ON public.sources(org_id, sync_status);
CREATE INDEX idx_source_grants_lookup ON public.source_access_grants(user_id, source_id, org_id);

-- Records & Versions
CREATE INDEX idx_records_lookup ON public.records(org_id, source_id, external_id);
CREATE INDEX idx_record_versions_hash ON public.record_versions(content_hash);
CREATE INDEX idx_record_versions_rec_latest ON public.record_versions(record_id, is_latest);
CREATE INDEX idx_record_versions_timeline ON public.record_versions(source_id, source_updated_at);

-- Vector Retrieval Index (HNSW, Cosine distance)
-- Note: Approximate vector search does not guarantee a fixed recall rate.
-- RLS acts as a post-filter on candidate nearest neighbors; application logic
-- must anticipate and handle underfilled result sets (< k results).
CREATE INDEX idx_chunks_embedding_hnsw ON public.chunks 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunks_version ON public.chunks(record_version_id);
CREATE INDEX idx_chunks_source_org ON public.chunks(source_id, org_id);

-- Graph & Audit Indexes
CREATE INDEX idx_links_from ON public.record_links(from_record_id, org_id);
CREATE INDEX idx_links_to ON public.record_links(to_record_id, org_id);
CREATE INDEX idx_claims_answer ON public.claims(answer_id);
CREATE INDEX idx_claims_version ON public.claims(record_version_id);

-- ----------------------------------------------------------------------------
-- 8. LEAST-PRIVILEGE PERMISSION GRANTS
-- ----------------------------------------------------------------------------

-- app_runtime (Interactive Web API role: reads evidence, writes user entities)
GRANT SELECT, UPDATE ON public.organizations TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.memberships TO app_runtime;
GRANT SELECT, INSERT, UPDATE ON public.sources TO app_runtime;
GRANT SELECT, INSERT, DELETE ON public.source_access_grants TO app_runtime;
GRANT SELECT ON public.records TO app_runtime;
GRANT SELECT ON public.record_versions TO app_runtime;
GRANT SELECT ON public.chunks TO app_runtime;
GRANT SELECT, INSERT, DELETE ON public.record_links TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.knowledge_notes TO app_runtime;
GRANT SELECT, INSERT, UPDATE ON public.knowledge_gaps TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.handoffs TO app_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.handoff_items TO app_runtime;
GRANT SELECT, INSERT, UPDATE ON public.answers TO app_runtime;
GRANT SELECT, INSERT ON public.claims TO app_runtime;

-- app_sync (Worker Ingest role: strictly ingestion & source metadata)
GRANT SELECT ON public.organizations TO app_sync;
GRANT SELECT ON public.memberships TO app_sync;
GRANT SELECT, UPDATE (sync_status, sync_cursor, last_synced_at, error_message, updated_at) ON public.sources TO app_sync;
GRANT SELECT, INSERT, UPDATE (title, url, author_name, author_email, is_deleted_upstream, metadata) ON public.records TO app_sync;
GRANT SELECT, INSERT, UPDATE (is_latest) ON public.record_versions TO app_sync;
GRANT SELECT, INSERT, DELETE ON public.chunks TO app_sync;
GRANT SELECT, INSERT, DELETE ON public.record_links TO app_sync;

-- Sequences usage for runtime roles
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_runtime, app_sync;
