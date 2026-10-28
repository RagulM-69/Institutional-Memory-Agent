-- Migration: 003_chunks_embedding_update_grant.sql
-- Description: Grant least-privilege column update on public.chunks(embedding) to app_sync
--              and define tenant-scoped RLS UPDATE policy for worker embedding backfill.

-- 1. Grant column-level UPDATE on chunks(embedding) only
GRANT UPDATE (embedding) ON public.chunks TO app_sync;

-- 2. Define explicit RLS UPDATE policy scoped to current tenant
CREATE POLICY chunks_worker_update_policy ON public.chunks
    FOR UPDATE TO app_sync
    USING (org_id = public.current_app_org())
    WITH CHECK (org_id = public.current_app_org());

