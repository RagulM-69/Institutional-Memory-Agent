-- ============================================================================
-- 002_user_memberships_helper.sql: Helper to resolve authenticated user's memberships
-- ============================================================================

CREATE OR REPLACE FUNCTION public.get_user_memberships()
RETURNS TABLE (org_id uuid, role text, name text, slug text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
  SELECT m.org_id, m.role, o.name, o.slug
  FROM public.memberships m
  JOIN public.organizations o ON o.id = m.org_id
  WHERE m.user_id = public.current_app_user();
$$;

ALTER FUNCTION public.get_user_memberships() OWNER TO postgres;
REVOKE ALL ON FUNCTION public.get_user_memberships() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_user_memberships() TO app_runtime;

