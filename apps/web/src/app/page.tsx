"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  AlertCircle,
  HelpCircle,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  Server,
  Layers,
  ArrowRight,
  Database,
  ExternalLink,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { QuestionComposer } from "@/components/ask/QuestionComposer";
import { AnswerView } from "@/components/ask/AnswerView";
import { SourceRetrievalAnimation } from "@/components/ask/SourceRetrievalAnimation";
import { AuthModal } from "@/components/auth/AuthModal";
import { BrandLogo, GitHubLogo, JiraLogo, SlackLogo } from "@/components/common/BrandLogos";
import {
  ActiveOrganization,
  ApiErrorDetail,
  AskResponse,
  AuthenticatedUser,
} from "@/lib/types";
import {
  askQuestion,
  checkApiHealth,
  getCurrentOrg,
  getCurrentUser,
  ApiError,
  API_BASE_URL,
} from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

export default function AskWorkspace() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Question & Answer state
  const [activeQuestion, setActiveQuestion] = useState<string>("");
  const [isAnswering, setIsAnswering] = useState<boolean>(false);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [errorDetail, setErrorDetail] = useState<ApiErrorDetail | null>(null);

  // Load authentication & backend session
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
        } catch (e) {
          console.warn("Could not fetch user profile from FastAPI:", e);
          if (e instanceof ApiError && e.status === 401) {
            setJwt(null);
            setUser(null);
            setOrg(null);
            return;
          }
        }

        try {
          const o = await getCurrentOrg(token);
          setOrg(o);
        } catch (e) {
          console.warn("Could not fetch active organization from FastAPI:", e);
          if (e instanceof ApiError && e.status === 403) {
            setOrg(null);
          }
        }
      } else {
        setUser(null);
        setOrg(null);
      }
    } catch (err) {
      console.error("Session refresh error:", err);
    } finally {
      setIsAuthLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function init() {
      if (!cancelled) {
        await refreshSession();
      }
    }

    void init();

    const sb = getSupabase();
    if (sb) {
      const {
        data: { subscription },
      } = sb.auth.onAuthStateChange(() => {
        if (!cancelled) {
          void refreshSession();
        }
      });
      return () => {
        cancelled = true;
        subscription.unsubscribe();
      };
    }

    return () => {
      cancelled = true;
    };
  }, [refreshSession]);

  const handleSignOut = async () => {
    const sb = getSupabase();
    if (sb) {
      await sb.auth.signOut();
    }
    setJwt(null);
    setUser(null);
    setOrg(null);
    setResponse(null);
    setErrorDetail(null);
  };

  const handleAsk = async (questionText: string) => {
    setErrorDetail(null);
    setActiveQuestion(questionText);

    // If user is not authenticated, prompt sign-in
    if (!jwt) {
      setErrorDetail({
        message: "Authentication required",
        status: 401,
        isRecoverable: true,
        recoveryHint:
          "Please sign in with your Supabase organization account to submit queries.",
      });
      setIsAuthModalOpen(true);
      return;
    }

    // If user has no active organization membership, do not execute
    if (!org) {
      setErrorDetail({
        message: "Organization membership required",
        status: 403,
        isRecoverable: false,
        recoveryHint:
          "Your account is authenticated but not assigned to an organization. Please run the owner bootstrap script or contact your administrator.",
      });
      return;
    }

    setIsAnswering(true);

    try {
      const res = await askQuestion(questionText, jwt, org?.org_id, true);
      setResponse(res);
      setErrorDetail(null);
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        setErrorDetail({
          message: err.message,
          status: err.status,
          isRecoverable: err.status !== 401 && err.status !== 403,
          recoveryHint: err.recoveryHint,
        });
        if (err.status === 401) {
          setIsAuthModalOpen(true);
        }
      } else {
        setErrorDetail({
          message:
            err instanceof Error ? err.message : "Failed to execute query.",
          status: 500,
          isRecoverable: true,
          recoveryHint: `Please verify that the FastAPI backend (${API_BASE_URL}) is online and reachable.`,
        });
      }
    } finally {
      setIsAnswering(false);
    }
  };

  const handleReset = () => {
    setResponse(null);
    setErrorDetail(null);
    setActiveQuestion("");
  };

  return (
    <div className="flex min-h-screen bg-[#fcfcfd] text-neutral-900 font-sans selection:bg-neutral-200">
      {/* Sidebar Navigation */}
      <AppSidebar
        currentPath="/"
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        apiOnline={apiOnline}
        org={org}
        user={user}
        onSignOut={handleSignOut}
      />

      {/* Main Workspace Column */}
      <div className="flex-1 flex flex-col min-w-0">
        <AppHeader
          user={user}
          org={org}
          onOpenSidebar={() => setIsSidebarOpen(true)}
          onSignOut={handleSignOut}
          onSignIn={() => setIsAuthModalOpen(true)}
        />

        <main className="flex-1 px-4 py-8 sm:px-8 max-w-5xl w-full mx-auto space-y-8">
          {/* Header Title & Intro Banner */}
          {!response && !isAnswering && (
            <div className="space-y-6 pt-2">
              <div className="space-y-2">
                <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight text-neutral-900 leading-tight">
                  Knowledge Search
                </h1>

                <p className="text-sm text-neutral-500 leading-relaxed max-w-2xl font-normal">
                  Search architectural decisions, pull requests, tickets, and team discussions across your engineering tools.
                </p>
              </div>

              {/* Interactive Connected Sources Ribbon */}
              <div className="space-y-2.5">
                <div className="flex items-center justify-between text-xs text-neutral-500 font-medium px-0.5">
                  <span className="uppercase tracking-wider text-[11px] text-neutral-400 font-semibold">
                    Live Integrated Knowledge Sources
                  </span>
                  <Link
                    href="/sources"
                    className="inline-flex items-center gap-1 text-neutral-600 hover:text-neutral-900 transition-colors font-medium"
                  >
                    <span>Manage sources</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </Link>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {/* GitHub Card */}
                  <Link
                    href="/sources"
                    className="group relative rounded-xl border border-neutral-200/90 bg-white p-4 shadow-2xs hover:shadow-xs hover:border-neutral-300 transition-all duration-150 flex flex-col justify-between"
                  >
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-neutral-900 text-white flex items-center justify-center shadow-xs">
                            <GitHubLogo className="w-4 h-4 text-white" />
                          </div>
                          <div>
                            <span className="text-xs font-semibold text-neutral-900 group-hover:text-blue-600 transition-colors">
                              GitHub
                            </span>
                            <span className="block text-[11px] text-neutral-400 font-mono">
                              gowthaman1205/Continuity
                            </span>
                          </div>
                        </div>
                        <span className="w-2 h-2 rounded-full bg-emerald-500" title="Operational" />
                      </div>
                      <p className="text-xs text-neutral-500 leading-snug">
                        Commits, PR diff reviews, and engineering commit messages.
                      </p>
                    </div>
                    <div className="pt-3 mt-1 border-t border-neutral-100 flex items-center justify-between text-[11px] text-neutral-400">
                      <span className="font-mono">4 Commits Synced</span>
                      <span className="text-neutral-600 group-hover:translate-x-0.5 transition-transform">→</span>
                    </div>
                  </Link>

                  {/* Jira Card */}
                  <Link
                    href="/sources"
                    className="group relative rounded-xl border border-neutral-200/90 bg-white p-4 shadow-2xs hover:shadow-xs hover:border-neutral-300 transition-all duration-150 flex flex-col justify-between"
                  >
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-blue-50 border border-blue-200/80 flex items-center justify-center shadow-xs">
                            <JiraLogo className="w-4 h-4" />
                          </div>
                          <div>
                            <span className="text-xs font-semibold text-neutral-900 group-hover:text-blue-600 transition-colors">
                              Jira Cloud
                            </span>
                            <span className="block text-[11px] text-neutral-400 font-mono">
                              Project KAN
                            </span>
                          </div>
                        </div>
                        <span className="w-2 h-2 rounded-full bg-emerald-500" title="Operational" />
                      </div>
                      <p className="text-xs text-neutral-500 leading-snug">
                        Tasks, subtasks, descriptions, assignees, and resolution status.
                      </p>
                    </div>
                    <div className="pt-3 mt-1 border-t border-neutral-100 flex items-center justify-between text-[11px] text-neutral-400">
                      <span className="font-mono">3 Tickets Synced</span>
                      <span className="text-neutral-600 group-hover:translate-x-0.5 transition-transform">→</span>
                    </div>
                  </Link>

                  {/* Slack Card */}
                  <Link
                    href="/sources"
                    className="group relative rounded-xl border border-neutral-200/90 bg-white p-4 shadow-2xs hover:shadow-xs hover:border-neutral-300 transition-all duration-150 flex flex-col justify-between"
                  >
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-lg bg-emerald-50/70 border border-emerald-200/80 flex items-center justify-center shadow-xs">
                            <SlackLogo className="w-4 h-4" />
                          </div>
                          <div>
                            <span className="text-xs font-semibold text-neutral-900 group-hover:text-emerald-700 transition-colors">
                              Slack Workspace
                            </span>
                            <span className="block text-[11px] text-neutral-400 font-mono">
                              #handoff-discussion
                            </span>
                          </div>
                        </div>
                        <span className="w-2 h-2 rounded-full bg-emerald-500" title="Operational" />
                      </div>
                      <p className="text-xs text-neutral-500 leading-snug">
                        Channel discussions, architectural consensus, and thread decisions.
                      </p>
                    </div>
                    <div className="pt-3 mt-1 border-t border-neutral-100 flex items-center justify-between text-[11px] text-neutral-400">
                      <span className="font-mono">13 Messages Synced</span>
                      <span className="text-neutral-600 group-hover:translate-x-0.5 transition-transform">→</span>
                    </div>
                  </Link>
                </div>
              </div>
            </div>
          )}

          {/* Active Error Banner */}
          {errorDetail && (
            <div
              role="alert"
              className="rounded-xl border border-rose-200 bg-rose-50/70 p-4 text-xs text-rose-900 space-y-2 animate-in fade-in"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2.5">
                  <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 shrink-0" />
                  <div>
                    <h3 className="font-semibold text-rose-950 text-xs uppercase tracking-wide">
                      Query Execution Notice (Status {errorDetail.status})
                    </h3>
                    <p className="text-rose-900 mt-0.5 leading-relaxed font-mono text-[11.5px]">
                      {errorDetail.message}
                    </p>
                    {errorDetail.recoveryHint && (
                      <p className="text-rose-800/90 mt-1 font-sans text-xs">
                        <strong>Remediation:</strong> {errorDetail.recoveryHint}
                      </p>
                    )}
                  </div>
                </div>

                {errorDetail.isRecoverable && activeQuestion && (
                  <button
                    type="button"
                    onClick={() => handleAsk(activeQuestion)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-rose-100 hover:bg-rose-200 text-rose-900 font-medium text-xs transition-colors shrink-0"
                  >
                    <RefreshCw className="w-3 h-3" />
                    <span>Retry</span>
                  </button>
                )}
              </div>
            </div>
          )}

          {/* While Answering: Dynamic Floating Multi-Source Retrieval Animation */}
          {isAnswering && (
            <SourceRetrievalAnimation question={activeQuestion} />
          )}

          {/* Answer Presentation */}
          {response && !isAnswering && (
            <AnswerView
              response={response}
              onReset={handleReset}
              jwt={jwt}
              orgId={org?.org_id}
            />
          )}

          {/* Question Composer */}
          {!response && !isAnswering && (
            <div className="pt-1">
              <QuestionComposer
                onSubmit={handleAsk}
                isLoading={isAnswering}
                disabled={isAuthLoading || !jwt || !org}
              />
            </div>
          )}

          {/* Authenticated but Missing Organization Membership */}
          {jwt && !org && !isAuthLoading && !response && !isAnswering && (
            <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 text-xs text-amber-900 space-y-2 animate-in fade-in">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2.5">
                  <ShieldAlert className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                  <div className="space-y-1">
                    <h3 className="font-semibold text-amber-950 text-xs uppercase tracking-wide">
                      No Active Organization Membership
                    </h3>
                    <p className="text-amber-900 text-xs leading-relaxed">
                      Signed in as <span className="font-medium font-mono">{user?.email || "authenticated user"}</span>, but your account is not yet assigned to an organization.
                    </p>
                    <code className="block mt-1 p-1.5 rounded bg-amber-100/90 font-mono text-[11px] text-amber-950 select-all border border-amber-200/70">
                      python -m apps.api.scripts.bootstrap_owner --email {user?.email || "owner@institutional-memory.local"} --org-name &quot;Your Team&quot; --org-slug &quot;your-team&quot;
                    </code>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={refreshSession}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-amber-200/80 hover:bg-amber-300 text-amber-950 font-medium text-xs transition-colors shrink-0 shadow-2xs"
                >
                  <RefreshCw className="w-3 h-3" />
                  <span>Refresh</span>
                </button>
              </div>
            </div>
          )}

          {/* Unauthenticated Explanatory State */}
          {!jwt && !isAuthLoading && !response && !isAnswering && (
            <div className="rounded-xl border border-neutral-200 bg-neutral-50/60 p-4 text-xs text-neutral-600 flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <HelpCircle className="w-4 h-4 text-neutral-400 shrink-0" />
                <span>
                  Query execution requires Supabase authentication to enforce
                  tenant-isolated row-level security.
                </span>
              </div>
              <button
                type="button"
                onClick={() => setIsAuthModalOpen(true)}
                className="inline-flex items-center gap-1 font-semibold text-neutral-900 hover:text-blue-600 transition-colors shrink-0"
              >
                <span>Sign in to query</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </main>
      </div>

      {/* Supabase Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onSuccess={refreshSession}
      />
    </div>
  );
}
