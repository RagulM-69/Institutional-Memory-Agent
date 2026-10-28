-- Migration: 004_knowledge_notes_record_links.sql
-- Description: Knowledge notes junction table, meeting-source unique index, and app_sync meeting insert policy.

-- 1. Create junction table for linking knowledge notes to source records
CREATE TABLE IF NOT EXISTS public.knowledge_note_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    note_id UUID NOT NULL,
    record_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_note_records_note FOREIGN KEY (note_id, org_id)
        REFERENCES public.knowledge_notes(id, org_id) ON DELETE CASCADE,
    CONSTRAINT fk_note_records_record FOREIGN KEY (record_id, org_id)
        REFERENCES public.records(id, org_id) ON DELETE CASCADE,
    CONSTRAINT uq_note_records_note_record_org UNIQUE (note_id, record_id, org_id)
);

CREATE INDEX IF NOT EXISTS idx_note_records_org_note ON public.knowledge_note_records(org_id, note_id);
CREATE INDEX IF NOT EXISTS idx_note_records_org_record ON public.knowledge_note_records(org_id, record_id);

-- 2. RLS for knowledge_note_records
ALTER TABLE public.knowledge_note_records ENABLE ROW LEVEL SECURITY;

CREATE POLICY note_records_select_policy ON public.knowledge_note_records
    FOR SELECT TO app_runtime
    USING (org_id = public.current_app_org());

CREATE POLICY note_records_insert_policy ON public.knowledge_note_records
    FOR INSERT TO app_runtime
    WITH CHECK (
        org_id = public.current_app_org()
        AND (
            EXISTS (
                SELECT 1 FROM public.knowledge_notes
                WHERE id = note_id
                  AND org_id = public.current_app_org()
                  AND author_user_id = public.current_app_user()
            )
            OR public.is_org_admin(org_id)
        )
    );

CREATE POLICY note_records_delete_policy ON public.knowledge_note_records
    FOR DELETE TO app_runtime
    USING (
        org_id = public.current_app_org()
        AND (
            EXISTS (
                SELECT 1 FROM public.knowledge_notes
                WHERE id = note_id
                  AND org_id = public.current_app_org()
                  AND author_user_id = public.current_app_user()
            )
            OR public.is_org_admin(org_id)
        )
    );

-- Least privilege: grant SELECT, INSERT, DELETE only (no UPDATE)
GRANT SELECT, INSERT, DELETE ON public.knowledge_note_records TO app_runtime;

-- 3. Concurrency-safe unique index for meeting sources
CREATE UNIQUE INDEX IF NOT EXISTS uq_sources_org_meeting
ON public.sources(org_id, type)
WHERE type = 'meeting' AND is_archived = false;

-- 4. Grant app_sync least-privilege INSERT on sources restricted strictly to meeting sources
GRANT INSERT ON public.sources TO app_sync;

CREATE POLICY sources_worker_insert_meeting_policy ON public.sources
    FOR INSERT TO app_sync
    WITH CHECK (
        org_id = public.current_app_org()
        AND type = 'meeting'
    );

