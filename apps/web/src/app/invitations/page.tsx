"use client";

import React, { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Building,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Lock,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { AuthModal } from "@/components/auth/AuthModal";
import {
  ActiveOrganization,
  AuthenticatedUser,
  InvitationLookupResponse,
  PendingUserInvitation,
} from "@/lib/types";
import {
  checkApiHealth,
  getCurrentOrg,
  getCurrentUser,
  lookupInvitation,
  acceptInvitation,
  declineInvitation,
  listMyPendingInvitations,
  ApiError,
} from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

function InvitationsContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Invitation lookup state
  const [inputCode, setInputCode] = useState<string>(
    searchParams.get("code") || searchParams.get("token") || ""
  );
  const [lookupResult, setLookupResult] = useState<InvitationLookupResponse | null>(null);
  const [isLookingUp, setIsLookingUp] = useState<boolean>(false);
  const [isAccepting, setIsAccepting] = useState<boolean>(false);
  const [isDeclining, setIsDeclining] = useState<boolean>(false);

  // Pending for user
  const [myPending, setMyPending] = useState<PendingUserInvitation[]>([]);

  // Feedback messages
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const refreshSession = useCallback(async () => {
    try {
      const isHealthy = await checkApiHealth();
      setApiOnline(isHealthy);

      const token = await getAccessToken();
      setJwt(token);

      if (token) {
        try {
          const u = await getCurrentUser(token);
          setUser(u);
        } catch {
          setUser(null);
        }

        try {
          const o = await getCurrentOrg(token);
          setOrg(o);
        } catch {
          setOrg(null);
        }
      } else {
        setUser(null);
        setOrg(null);
      }
    } catch {
      setApiOnline(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      if (!cancelled) await refreshSession();
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [refreshSession]);

  // Load pending invites for user
  const loadPendingForMe = useCallback(async () => {
    if (!jwt) return;
    try {
      const pending = await listMyPendingInvitations(jwt);
      setMyPending(pending);
    } catch {
      // silently ignore if failed
    }
  }, [jwt]);

  useEffect(() => {
    let cancelled = false;
    async function initPending() {
      if (!cancelled && jwt) {
        await loadPendingForMe();
      }
    }
    initPending();
    return () => {
      cancelled = true;
    };
  }, [jwt, loadPendingForMe]);

  // Perform lookup
  const handleLookup = useCallback(
    async (codeToLookup?: string) => {
      const target = (codeToLookup ?? inputCode).trim();
      if (!target || !jwt) return;

      setIsLookingUp(true);
      setErrorMsg(null);
      setLookupResult(null);

      const isToken = target.length > 30 && !target.startsWith("INV-");
      const payload = isToken ? { token: target } : { code: target };

      try {
        const res = await lookupInvitation(payload, jwt);
        setLookupResult(res);
      } catch (err) {
        setLookupResult(null);
        if (err instanceof ApiError) {
          setErrorMsg(err.message);
        } else {
          setErrorMsg("Failed to lookup invitation.");
        }
      } finally {
        setIsLookingUp(false);
      }
    },
    [inputCode, jwt]
  );

  // Auto-lookup if code or token is in URL
  useEffect(() => {
    let cancelled = false;
    const urlCode = searchParams.get("code") || searchParams.get("token");
    if (urlCode && jwt) {
      const timer = setTimeout(() => {
        if (!cancelled) {
          handleLookup(urlCode);
        }
      }, 0);
      return () => {
        cancelled = true;
        clearTimeout(timer);
      };
    }
  }, [searchParams, jwt, handleLookup]);

  // Handle Accept
  const handleAccept = async (opts?: { invitation_id?: string; code?: string }) => {
    if (!jwt) return;
    setIsAccepting(true);
    setErrorMsg(null);

    let payload: { invitation_id?: string; code_or_token?: string; code?: string; token?: string };
    if (opts?.invitation_id) {
      payload = { invitation_id: opts.invitation_id };
    } else {
      const code = (opts?.code ?? inputCode).trim();
      if (!code) {
        setIsAccepting(false);
        return;
      }
      payload = { code_or_token: code };
    }

    try {
      const res = await acceptInvitation(payload, jwt);
      setSuccessMsg(`Welcome to ${res.org_name}! You are now a ${res.role}.`);
      setLookupResult(null);
      setInputCode("");
      await refreshSession();
      await loadPendingForMe();
      setTimeout(() => {
        router.push("/team");
      }, 1500);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to accept invitation.");
      }
    } finally {
      setIsAccepting(false);
    }
  };

  // Handle Decline
  const handleDecline = async (opts?: { invitation_id?: string; code?: string }) => {
    if (!jwt) return;
    setIsDeclining(true);
    setErrorMsg(null);

    let payload: { invitation_id?: string; code_or_token?: string; code?: string; token?: string };
    if (opts?.invitation_id) {
      payload = { invitation_id: opts.invitation_id };
    } else {
      const code = (opts?.code ?? inputCode).trim();
      if (!code) {
        setIsDeclining(false);
        return;
      }
      payload = { code_or_token: code };
    }

    try {
      await declineInvitation(payload, jwt);
      setSuccessMsg("Invitation declined.");
      setLookupResult(null);
      setInputCode("");
      await loadPendingForMe();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to decline invitation.");
      }
    } finally {
      setIsDeclining(false);
    }
  };

  const emailMismatch = Boolean(
    user &&
      lookupResult &&
      (lookupResult.email_matches === false ||
        (!lookupResult.email_matches &&
          lookupResult.email &&
          !lookupResult.email.includes("***") &&
          user.email?.toLowerCase() !== lookupResult.email.toLowerCase()))
  );

  return (
    <div className="flex h-screen bg-[#fafafa] text-neutral-900 overflow-hidden font-sans">
      <AppSidebar
        currentPath="/team"
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        apiOnline={apiOnline}
        org={org}
        user={user}
        onSignOut={() => {
          const sb = getSupabase();
          if (sb) sb.auth.signOut();
          setJwt(null);
          setUser(null);
          setOrg(null);
        }}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <AppHeader
          user={user}
          org={org}
          apiOnline={apiOnline}
          onOpenAuth={() => setIsAuthModalOpen(true)}
          onSignOut={() => {
            const sb = getSupabase();
            if (sb) sb.auth.signOut();
            setJwt(null);
            setUser(null);
            setOrg(null);
          }}
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        />

        <main className="flex-1 overflow-y-auto p-4 md:p-8">
          <div className="max-w-2xl mx-auto space-y-6">
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-neutral-900">
                Organization Invitations
              </h1>
              <p className="text-sm text-neutral-500 mt-1">
                Accept an invitation to join an existing organization or enter a secret invitation code.
              </p>
            </div>

            {/* Notifications */}
            {errorMsg && (
              <div className="flex items-start gap-3 p-3.5 rounded-lg bg-red-50 border border-red-200 text-red-800 text-sm">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-600" />
                <div className="flex-1">{errorMsg}</div>
              </div>
            )}

            {successMsg && (
              <div className="flex items-start gap-3 p-3.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
                <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" />
                <div className="flex-1">{successMsg}</div>
              </div>
            )}

            {!user ? (
              <div className="p-6 bg-white border border-neutral-200/80 rounded-xl text-center space-y-4 shadow-2xs">
                <div className="w-12 h-12 rounded-full bg-neutral-100 mx-auto flex items-center justify-center text-neutral-600">
                  <Lock className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-semibold text-neutral-900">Sign in required</h3>
                  <p className="text-xs text-neutral-500 mt-1">
                    Please sign in or create an account with your invited email address to review and accept invitations.
                  </p>
                </div>
                <button
                  onClick={() => setIsAuthModalOpen(true)}
                  className="px-4 py-2 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg inline-flex items-center gap-1.5"
                >
                  Sign In to Continue
                </button>
              </div>
            ) : (
              <>
                {/* Pending for me list */}
                {myPending.length > 0 && (
                  <div className="bg-white border border-neutral-200/80 rounded-xl p-5 shadow-2xs space-y-3">
                    <h3 className="text-xs font-bold uppercase tracking-wider text-neutral-500">
                      Pending Invitations for {user.email}
                    </h3>
                    <div className="divide-y divide-neutral-100">
                      {myPending.map((p) => (
                        <div
                          key={p.id}
                          className="py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                        >
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="font-semibold text-sm text-neutral-900">
                                {p.org_name}
                              </span>
                              <span className="text-xs text-neutral-400 font-mono">
                                /{p.org_slug}
                              </span>
                              <span className="text-xs px-2 py-0.5 rounded-full bg-neutral-100 font-medium">
                                {p.role}
                              </span>
                            </div>
                            <span className="text-xs text-neutral-400">
                              Expires {new Date(p.expires_at).toLocaleDateString()}
                            </span>
                          </div>

                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => {
                                handleAccept({ invitation_id: p.id });
                              }}
                              disabled={isAccepting}
                              className="px-3 py-1.5 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg disabled:opacity-50 flex items-center gap-1"
                            >
                              {isAccepting && <Loader2 className="w-3 h-3 animate-spin" />}
                              Accept
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Lookup Card */}
                <div className="bg-white border border-neutral-200/80 rounded-xl p-5 shadow-2xs space-y-4">
                  <h3 className="text-sm font-bold text-neutral-900">
                    Lookup Invitation by Code or Link Token
                  </h3>

                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      placeholder="e.g. INV-ABCD-EFGH-1234 or paste link token"
                      value={inputCode}
                      onChange={(e) => setInputCode(e.target.value)}
                      className="flex-1 text-xs border border-neutral-300 rounded-lg px-3 py-2 text-neutral-900 font-mono focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                    />
                    <button
                      onClick={() => handleLookup()}
                      disabled={isLookingUp || !inputCode.trim()}
                      className="px-4 py-2 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg disabled:opacity-50 flex items-center gap-1.5"
                    >
                      {isLookingUp && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                      Lookup
                    </button>
                  </div>

                  {lookupResult && (
                    <div className="mt-4 p-4 border border-neutral-200 rounded-lg bg-neutral-50/50 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Building className="w-4 h-4 text-neutral-700" />
                          <span className="font-bold text-sm text-neutral-900">
                            {lookupResult.org_name}
                          </span>
                          <span className="text-xs text-neutral-400 font-mono">
                            /{lookupResult.org_slug}
                          </span>
                        </div>
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-neutral-200 text-neutral-800">
                          {lookupResult.role}
                        </span>
                      </div>

                      <div className="text-xs text-neutral-600">
                        Issued to: <span className="font-mono font-medium">{lookupResult.masked_email || lookupResult.email}</span>
                      </div>

                      {emailMismatch ? (
                        <div className="p-3 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-xs flex items-start gap-2">
                          <AlertCircle className="w-4 h-4 shrink-0 text-amber-600 mt-0.5" />
                          <span>
                            Account mismatch: This invitation is addressed to{" "}
                            <strong>{lookupResult.masked_email || lookupResult.email}</strong>, but you are currently signed in as{" "}
                            <strong>{user.email}</strong>. Please switch accounts to accept.
                          </span>
                        </div>
                      ) : (
                        <div className="space-y-3 pt-1">
                          <div className="p-2.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs flex items-center gap-2">
                            <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                            <span>Verified for your account (<strong>{user?.email}</strong>)</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleAccept({ code: inputCode })}
                              disabled={isAccepting || !lookupResult.can_accept}
                              className="px-4 py-1.5 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg flex items-center gap-1.5 disabled:opacity-50"
                            >
                              {isAccepting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                              Accept Invitation
                            </button>
                            <button
                              onClick={() => handleDecline({ code: inputCode })}
                              disabled={isDeclining}
                              className="px-3.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-200 rounded-lg"
                            >
                              Decline
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </main>
      </div>

      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onSuccess={refreshSession}
      />
    </div>
  );
}

export default function InvitationsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center bg-[#fafafa]">
          <Loader2 className="w-6 h-6 animate-spin text-neutral-400" />
        </div>
      }
    >
      <InvitationsContent />
    </Suspense>
  );
}
