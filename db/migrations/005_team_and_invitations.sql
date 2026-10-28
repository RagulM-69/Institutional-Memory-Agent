-- ============================================================================
-- 005_team_and_invitations.sql: Organization Onboarding, Invitations & Team Lead
-- ============================================================================

-- 1. Expand role check constraint on public.memberships to support 'team_lead'
ALTER TABLE public.memberships DROP CONSTRAINT IF EXISTS memberships_role_check;
ALTER TABLE public.memberships ADD CONSTRAINT memberships_role_check
    CHECK (role IN ('admin', 'team_lead', 'member'));

-- 2. Concurrency-Safe Last Admin Protection Trigger on public.memberships
CREATE OR REPLACE FUNCTION public.enforce_last_admin_protection()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_admin_count INT;
    v_org_exists BOOLEAN;
BEGIN
    -- Only protect when an existing admin row is being deleted or demoted
    IF OLD.role = 'admin' AND (TG_OP = 'DELETE' OR NEW.role != 'admin') THEN
        -- Allow cascade delete when the parent organization itself is deleted
        SELECT EXISTS (SELECT 1 FROM public.organizations WHERE id = OLD.org_id) INTO v_org_exists;
        IF NOT v_org_exists THEN
            RETURN COALESCE(NEW, OLD);
        END IF;

        -- Serialize on the parent organization row to eliminate concurrent demotion races
        PERFORM 1 FROM public.organizations WHERE id = OLD.org_id FOR UPDATE;

        SELECT COUNT(*) INTO v_admin_count
        FROM public.memberships
        WHERE org_id = OLD.org_id AND role = 'admin' AND id != OLD.id;

        IF v_admin_count < 1 THEN
            RAISE EXCEPTION 'Cannot demote or remove the last administrator of organization %', OLD.org_id
                USING ERRCODE = 'P0001';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_last_admin ON public.memberships;
CREATE TRIGGER trg_enforce_last_admin
    BEFORE UPDATE OR DELETE ON public.memberships
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_last_admin_protection();

-- 3. Add assignee and due date to public.handoff_items
ALTER TABLE public.handoff_items 
    ADD COLUMN IF NOT EXISTS assignee_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS due_date TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_handoff_items_assignee 
    ON public.handoff_items(org_id, assignee_user_id) 
    WHERE assignee_user_id IS NOT NULL;

-- 4. Create public.invitations table with dual hashes at rest
CREATE TABLE IF NOT EXISTS public.invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    invited_email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'team_lead', 'member')),
    token_hash TEXT NOT NULL UNIQUE,
    code_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending' 
        CHECK (status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')),
    created_by_user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    accepted_by_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 days'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Performance & Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_invitations_org_status ON public.invitations(org_id, status);
CREATE INDEX IF NOT EXISTS idx_invitations_email_status ON public.invitations(lower(invited_email), status);
CREATE INDEX IF NOT EXISTS idx_invitations_token_hash ON public.invitations(token_hash);
CREATE INDEX IF NOT EXISTS idx_invitations_code_hash ON public.invitations(code_hash);

-- Enable RLS on invitations
ALTER TABLE public.invitations ENABLE ROW LEVEL SECURITY;

-- Invitations RLS for app_runtime (Admin-only management; non-admins interact via SECURITY DEFINER functions)
DROP POLICY IF EXISTS invitations_admin_select ON public.invitations;
CREATE POLICY invitations_admin_select ON public.invitations
    FOR SELECT TO app_runtime
    USING (org_id = current_app_org() AND is_org_admin(org_id));

DROP POLICY IF EXISTS invitations_admin_insert ON public.invitations;
CREATE POLICY invitations_admin_insert ON public.invitations
    FOR INSERT TO app_runtime
    WITH CHECK (org_id = current_app_org() AND is_org_admin(org_id));

DROP POLICY IF EXISTS invitations_admin_update ON public.invitations;
CREATE POLICY invitations_admin_update ON public.invitations
    FOR UPDATE TO app_runtime
    USING (org_id = current_app_org() AND is_org_admin(org_id))
    WITH CHECK (org_id = current_app_org() AND is_org_admin(org_id));

DROP POLICY IF EXISTS invitations_admin_delete ON public.invitations;
CREATE POLICY invitations_admin_delete ON public.invitations
    FOR DELETE TO app_runtime
    USING (org_id = current_app_org() AND is_org_admin(org_id));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.invitations TO app_runtime;

-- 5. Safe Security-Definer Function: Organization Onboarding with Creator Admin
CREATE OR REPLACE FUNCTION public.create_organization_with_owner(
    p_name TEXT,
    p_slug TEXT
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_user_id UUID;
    v_org_id UUID;
BEGIN
    v_user_id := public.current_app_user();
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required to create an organization' USING ERRCODE = 'P0006';
    END IF;

    IF p_slug !~ '^[a-z0-9-]+$' OR length(p_slug) < 3 OR length(p_slug) > 48 THEN
        RAISE EXCEPTION 'Slug must be 3-48 lowercase alphanumeric characters or hyphens' USING ERRCODE = 'P0008';
    END IF;

    INSERT INTO public.organizations (name, slug)
    VALUES (trim(p_name), trim(lower(p_slug)))
    RETURNING id INTO v_org_id;

    INSERT INTO public.memberships (org_id, user_id, role)
    VALUES (v_org_id, v_user_id, 'admin');

    RETURN v_org_id;
END;
$$;

ALTER FUNCTION public.create_organization_with_owner(TEXT, TEXT) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.create_organization_with_owner(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.create_organization_with_owner(TEXT, TEXT) TO app_runtime;

-- 6. Safe Security-Definer Function: Retrieve Pending Invites for Authenticated User
CREATE OR REPLACE FUNCTION public.get_my_pending_invitations()
RETURNS TABLE (
    id UUID,
    org_id UUID,
    org_name TEXT,
    org_slug TEXT,
    invited_email TEXT,
    role TEXT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    SELECT i.id, i.org_id, o.name AS org_name, o.slug AS org_slug,
           i.invited_email, i.role, i.expires_at, i.created_at
    FROM public.invitations i
    JOIN public.organizations o ON o.id = i.org_id
    JOIN auth.users u ON u.id = public.current_app_user()
    WHERE lower(i.invited_email) = lower(u.email)
      AND i.status = 'pending'
      AND i.expires_at > now()
    ORDER BY i.created_at DESC;
$$;

ALTER FUNCTION public.get_my_pending_invitations() OWNER TO postgres;
REVOKE ALL ON FUNCTION public.get_my_pending_invitations() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_my_pending_invitations() TO app_runtime;

-- 7. Safe Security-Definer Function: Atomic Invitation Acceptance
CREATE OR REPLACE FUNCTION public.accept_organization_invitation(
    p_hash TEXT,
    p_hash_type TEXT
)
RETURNS TABLE (
    org_id UUID,
    org_name TEXT,
    role TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_user_id UUID;
    v_user_email TEXT;
    v_inv RECORD;
    v_org_name TEXT;
    v_existing_membership_role TEXT;
BEGIN
    v_user_id := public.current_app_user();
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required' USING ERRCODE = 'P0006';
    END IF;

    SELECT email INTO v_user_email FROM auth.users WHERE id = v_user_id;

    -- Pessimistic row-level lock on the invitation record
    IF p_hash_type = 'id' THEN
        SELECT * INTO v_inv FROM public.invitations WHERE id = p_hash::uuid FOR UPDATE;
    ELSIF p_hash_type = 'token' THEN
        SELECT * INTO v_inv FROM public.invitations WHERE token_hash = p_hash FOR UPDATE;
    ELSE
        SELECT * INTO v_inv FROM public.invitations WHERE code_hash = p_hash FOR UPDATE;
    END IF;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invitation not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_inv.status != 'pending' THEN
        RAISE EXCEPTION 'Invitation is no longer pending' USING ERRCODE = 'P0003';
    END IF;
    IF v_inv.expires_at <= now() THEN
        RAISE EXCEPTION 'Invitation has expired' USING ERRCODE = 'P0004';
    END IF;
    IF lower(v_user_email) != lower(v_inv.invited_email) THEN
        RAISE EXCEPTION 'Email mismatch: invitation was issued for %', v_inv.invited_email USING ERRCODE = 'P0005';
    END IF;

    -- Mandatory Safeguard: Reject if user is already a member of this organization.
    -- Never change or overwrite an existing membership role via invitation acceptance.
    SELECT m.role INTO v_existing_membership_role
    FROM public.memberships m
    WHERE m.org_id = v_inv.org_id AND m.user_id = v_user_id;

    IF v_existing_membership_role IS NOT NULL THEN
        RAISE EXCEPTION 'User is already a member of this organization' USING ERRCODE = 'P0007';
    END IF;

    -- Atomically transition invitation to accepted
    UPDATE public.invitations
    SET status = 'accepted', accepted_by_user_id = v_user_id, updated_at = now()
    WHERE id = v_inv.id;

    -- Atomically insert the new membership
    INSERT INTO public.memberships (org_id, user_id, role)
    VALUES (v_inv.org_id, v_user_id, v_inv.role);

    SELECT name INTO v_org_name FROM public.organizations WHERE id = v_inv.org_id;

    RETURN QUERY SELECT v_inv.org_id, v_org_name, v_inv.role;
END;
$$;

ALTER FUNCTION public.accept_organization_invitation(TEXT, TEXT) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.accept_organization_invitation(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.accept_organization_invitation(TEXT, TEXT) TO app_runtime;

-- 8. Safe Security-Definer Function: Decline Invitation
CREATE OR REPLACE FUNCTION public.decline_organization_invitation(
    p_hash TEXT,
    p_hash_type TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_user_id UUID;
    v_user_email TEXT;
    v_inv RECORD;
BEGIN
    v_user_id := public.current_app_user();
    IF v_user_id IS NULL THEN
        RAISE EXCEPTION 'Authentication required' USING ERRCODE = 'P0006';
    END IF;

    SELECT email INTO v_user_email FROM auth.users WHERE id = v_user_id;

    IF p_hash_type = 'id' THEN
        SELECT * INTO v_inv FROM public.invitations WHERE id = p_hash::uuid FOR UPDATE;
    ELSIF p_hash_type = 'token' THEN
        SELECT * INTO v_inv FROM public.invitations WHERE token_hash = p_hash FOR UPDATE;
    ELSE
        SELECT * INTO v_inv FROM public.invitations WHERE code_hash = p_hash FOR UPDATE;
    END IF;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Invitation not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_inv.status != 'pending' THEN
        RAISE EXCEPTION 'Invitation is no longer pending' USING ERRCODE = 'P0003';
    END IF;
    IF lower(v_user_email) != lower(v_inv.invited_email) THEN
        RAISE EXCEPTION 'Email mismatch: invitation was issued for %', v_inv.invited_email USING ERRCODE = 'P0005';
    END IF;

    UPDATE public.invitations
    SET status = 'declined', updated_at = now()
    WHERE id = v_inv.id;

    RETURN TRUE;
END;
$$;

ALTER FUNCTION public.decline_organization_invitation(TEXT, TEXT) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.decline_organization_invitation(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decline_organization_invitation(TEXT, TEXT) TO app_runtime;

-- 9. Directory Privacy: Member List with Restricted Email Access
CREATE OR REPLACE FUNCTION public.get_org_members(target_org_id UUID)
RETURNS TABLE (
    user_id UUID,
    email TEXT,
    role TEXT,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_caller_role TEXT;
BEGIN
    IF target_org_id != public.current_app_org() THEN
        RETURN;
    END IF;

    SELECT m.role INTO v_caller_role
    FROM public.memberships m
    WHERE m.org_id = target_org_id AND m.user_id = public.current_app_user();

    IF v_caller_role IN ('admin', 'team_lead') THEN
        RETURN QUERY
            SELECT m.user_id, u.email::text, m.role, m.created_at
            FROM public.memberships m
            JOIN auth.users u ON u.id = m.user_id
            WHERE m.org_id = target_org_id
            ORDER BY (m.role = 'admin') DESC, (m.role = 'team_lead') DESC, m.created_at ASC;
    ELSE
        -- Regular members only see their own identity
        RETURN QUERY
            SELECT m.user_id, u.email::text, m.role, m.created_at
            FROM public.memberships m
            JOIN auth.users u ON u.id = m.user_id
            WHERE m.org_id = target_org_id AND m.user_id = public.current_app_user();
    END IF;
END;
$$;

ALTER FUNCTION public.get_org_members(UUID) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.get_org_members(UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_org_members(UUID) TO app_runtime;

-- 10. Safe Security-Definer Function: Public Invitation Lookup by Hash or UUID
CREATE OR REPLACE FUNCTION public.lookup_invitation(p_hash TEXT)
RETURNS TABLE (
    id UUID,
    org_id UUID,
    org_name TEXT,
    org_slug TEXT,
    invited_email TEXT,
    role TEXT,
    status TEXT,
    expires_at TIMESTAMPTZ
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_hash ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
        RETURN QUERY
        SELECT i.id, i.org_id, o.name AS org_name, o.slug AS org_slug,
               i.invited_email, i.role, i.status, i.expires_at
        FROM public.invitations i
        JOIN public.organizations o ON o.id = i.org_id
        WHERE i.id = p_hash::uuid;
    ELSE
        RETURN QUERY
        SELECT i.id, i.org_id, o.name AS org_name, o.slug AS org_slug,
               i.invited_email, i.role, i.status, i.expires_at
        FROM public.invitations i
        JOIN public.organizations o ON o.id = i.org_id
        WHERE i.token_hash = p_hash OR i.code_hash = p_hash;
    END IF;
END;
$$;

ALTER FUNCTION public.lookup_invitation(TEXT) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.lookup_invitation(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.lookup_invitation(TEXT) TO app_runtime;
