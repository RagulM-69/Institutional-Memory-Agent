import { createClient, SupabaseClient } from "@supabase/supabase-js";

const supabaseUrl =
  process.env.NEXT_PUBLIC_SUPABASE_URL ||
  "https://vakimprsrxeoaewuiilk.supabase.co";
const supabaseAnonKey =
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ||
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZha2ltcHJzcnhlb2Fld3VpaWxrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMxMTI0NDgsImV4cCI6MjEwODY4ODQ0OH0.RqAFqY7z53ukzYEyrkePRLknW1w6wdiZ09Bh8yW_P6Y";

let client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (!supabaseUrl || !supabaseAnonKey) {
    if (typeof window !== "undefined") {
      console.warn("Supabase public credentials not configured in NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY");
    }
    return null;
  }

  if (!client) {
    client = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
      },
    });
  }

  return client;
}

export async function getAccessToken(): Promise<string | null> {
  const sb = getSupabase();
  if (!sb) return null;

  try {
    const { data: { session } } = await sb.auth.getSession();
    return session?.access_token || null;
  } catch (err) {
    console.error("Error retrieving Supabase auth token:", err);
    return null;
  }
}

