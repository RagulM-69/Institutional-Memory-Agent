"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Database,
  Plus,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Shield,
  ShieldAlert,
  Clock,
  ArrowRight,
  Lock,
  Layers,
  ExternalLink,
  FileText,
  Loader2,
  Archive,
  Eye,
  X,
  ChevronLeft,
  ChevronRight,
  Info,
  GitBranch,
  Check,
  Trash2,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { AuthModal } from "@/components/auth/AuthModal";
import { BrandLogo, GitHubLogo, JiraLogo, SlackLogo } from "@/components/common/BrandLogos";
import {
  ActiveOrganization,
  AuthenticatedUser,
  KnowledgeSource,
  SourceRecord,
  PaginatedSourceRecords,
  SourceType,
  SourceVisibility,
  OAuthStatusResponse,
  OAuthSessionResponse,
} from "@/lib/types";
import {
  checkApiHealth,
  getCurrentOrg,
  getCurrentUser,
  listSources,
  createSource,
  updateSource,
  syncSource,
  deleteSource,
  getSourceRecords,
  validateSourceConfig,
  getOAuthStatus,
  getOAuthAuthorizeUrl,
  getOAuthSession,
  finalizeOAuthSession,
  ApiError,
} from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

export default function SourcesPage() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Sources State
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [isLoadingSources, setIsLoadingSources] = useState<boolean>(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [syncingSourceIds, setSyncingSourceIds] = useState<Record<string, boolean>>({});

  // Filter
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [showArchived, setShowArchived] = useState<boolean>(false);

  // OAuth & Multi-Tenant Integration State
  const [oauthStatus, setOauthStatus] = useState<OAuthStatusResponse | null>(null);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const [oauthSessionId, setOauthSessionId] = useState<string | null>(null);
  const [oauthSessionData, setOauthSessionData] = useState<OAuthSessionResponse | null>(null);
  const [selectedTargetId, setSelectedTargetId] = useState<string>("");
  const [isFinalizingOAuth, setIsFinalizingOAuth] = useState<boolean>(false);
  const [oauthFinalizeError, setOauthFinalizeError] = useState<string | null>(null);

  // Connect Source Modal State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [connectionMethod, setConnectionMethod] = useState<"token" | "oauth">("token");
  const [newSourceName, setNewSourceName] = useState<string>("");
  const [newSourceType, setNewSourceType] = useState<SourceType>("github");
  const [newSourceVisibility, setNewSourceVisibility] = useState<SourceVisibility>("public");
  // GitHub config
  const [githubRepo, setGithubRepo] = useState<string>("");
  const [githubToken, setGithubToken] = useState<string>("");
  // Jira config
  const [jiraBaseUrl, setJiraBaseUrl] = useState<string>("");
  const [jiraProjectKey, setJiraProjectKey] = useState<string>("");
  const [jiraEmail, setJiraEmail] = useState<string>("");
  const [jiraToken, setJiraToken] = useState<string>("");
  // Slack config
  const [slackChannelId, setSlackChannelId] = useState<string>("");
  const [slackToken, setSlackToken] = useState<string>("");

  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [validationResult, setValidationResult] = useState<{
    is_valid: boolean;
    message: string;
  } | null>(null);
  const [isSubmittingCreate, setIsSubmittingCreate] = useState<boolean>(false);
  const [createModalError, setCreateModalError] = useState<string | null>(null);

  // Records Inspection Modal State
  const [inspectSource, setInspectSource] = useState<KnowledgeSource | null>(null);
  const [recordsData, setRecordsData] = useState<PaginatedSourceRecords | null>(null);
  const [isLoadingRecords, setIsLoadingRecords] = useState<boolean>(false);
  const [recordsOffset, setRecordsOffset] = useState<number>(0);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const recordsLimit = 15;

  const isAdmin = org?.role === "admin" || org?.role === "team_lead";

  // Refresh Session
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
        } catch {
          setOrg(null);
        }
      } else {
        setUser(null);
        setOrg(null);
      }
    } finally {
      setIsAuthLoading(false);
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

  const handleSignOut = async () => {
    const sb = getSupabase();
    if (sb) {
      await sb.auth.signOut();
    }
    setJwt(null);
    setUser(null);
    setOrg(null);
  };

  // Fetch Sources
  const fetchSources = useCallback(async () => {
    if (!jwt || !org) return;
    setIsLoadingSources(true);
    setGeneralError(null);
    try {
      const list = await listSources(jwt, org.org_id);
      setSources(list);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load sources";
      setGeneralError(msg);
    } finally {
      setIsLoadingSources(false);
    }
  }, [jwt, org]);

  useEffect(() => {
    let cancelled = false;
    async function executeLoad() {
      if (!cancelled && jwt && org) {
        await fetchSources();
      }
    }
    executeLoad();
    return () => {
      cancelled = true;
    };
  }, [jwt, org, fetchSources]);

  // Periodic polling if any source is in "running" sync_status
  const hasRunningSync = useMemo(
    () => sources.some((s) => s.sync_status === "running") || Object.values(syncingSourceIds).some(Boolean),
    [sources, syncingSourceIds]
  );

  useEffect(() => {
    if (!hasRunningSync || !jwt || !org) return;

    const interval = setInterval(async () => {
      try {
        const list = await listSources(jwt, org.org_id);
        setSources(list);
        // Clear local syncing flags if backend says no longer running
        setSyncingSourceIds((prev) => {
          const updated = { ...prev };
          for (const s of list) {
            if (s.sync_status !== "running" && updated[s.id]) {
              delete updated[s.id];
            }
          }
          return updated;
        });
      } catch {
        // silent background poll failure
      }
    }, 3500);

    return () => clearInterval(interval);
  }, [hasRunningSync, jwt, org]);

  // Load OAuth Provider status for current organization
  useEffect(() => {
    if (!jwt || !org) return;
    getOAuthStatus(jwt, org.org_id)
      .then(setOauthStatus)
      .catch(() => {});
  }, [jwt, org]);

  // Detect OAuth callback parameters from URL
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const session = params.get("oauth_session");
    const err = params.get("oauth_error");
    if (err) {
      const decoded = decodeURIComponent(err);
      setTimeout(() => setOauthError(decoded), 0);
      window.history.replaceState({}, document.title, window.location.pathname);
    } else if (session) {
      setTimeout(() => setOauthSessionId(session), 0);
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, []);

  // When oauthSessionId is present, fetch session target details
  useEffect(() => {
    if (!oauthSessionId || !jwt || !org) return;
    let active = true;
    async function loadSession() {
      try {
        const data = await getOAuthSession(oauthSessionId!, jwt!, org!.org_id);
        if (active) {
          setOauthSessionData(data);
          if (data.targets && data.targets.length > 0) {
            setSelectedTargetId(data.targets[0].id);
            setNewSourceName(`${data.targets[0].name}`);
          }
        }
      } catch (err: unknown) {
        if (active) {
          const msg = err instanceof Error ? err.message : "Failed to load OAuth session";
          setOauthError(msg);
          setOauthSessionId(null);
        }
      }
    }
    loadSession();
    return () => {
      active = false;
    };
  }, [oauthSessionId, jwt, org]);

  // Construct config object for new source
  const buildCurrentConfig = useCallback(() => {
    if (newSourceType === "github") {
      return { repo: githubRepo.trim() };
    }
    if (newSourceType === "jira") {
      return {
        base_url: jiraBaseUrl.trim(),
        project: jiraProjectKey.trim().toUpperCase(),
      };
    }
    if (newSourceType === "slack") {
      return { channel_id: slackChannelId.trim() };
    }
    return {};
  }, [newSourceType, githubRepo, jiraBaseUrl, jiraProjectKey, slackChannelId]);

  // Construct credentials object for direct per-organization token input
  const buildCurrentCredentials = useCallback((): Record<string, string> | undefined => {
    if (newSourceType === "github" && githubToken.trim()) {
      return { token: githubToken.trim() };
    }
    if (newSourceType === "jira" && (jiraEmail.trim() || jiraToken.trim())) {
      const creds: Record<string, string> = {};
      if (jiraEmail.trim()) creds["email"] = jiraEmail.trim();
      if (jiraToken.trim()) creds["token"] = jiraToken.trim();
      return creds;
    }
    if (newSourceType === "slack" && slackToken.trim()) {
      return { token: slackToken.trim() };
    }
    return undefined;
  }, [newSourceType, githubToken, jiraEmail, jiraToken, slackToken]);

  // Reset Create Form
  const resetCreateForm = () => {
    setNewSourceName("");
    setNewSourceType("github");
    setNewSourceVisibility("public");
    setConnectionMethod("token");
    setGithubRepo("");
    setGithubToken("");
    setJiraBaseUrl("");
    setJiraProjectKey("");
    setJiraEmail("");
    setJiraToken("");
    setSlackChannelId("");
    setSlackToken("");
    setValidationResult(null);
    setCreateModalError(null);
    setIsCreateModalOpen(false);
  };

  // Test Connection
  const handleValidateConfig = async () => {
    if (!jwt || !org) return;
    setIsValidating(true);
    setValidationResult(null);
    setCreateModalError(null);

    const config = buildCurrentConfig();
    const credentials = buildCurrentCredentials();
    try {
      const res = await validateSourceConfig(
        { type: newSourceType, config, credentials },
        jwt,
        org.org_id
      );
      setValidationResult(res);
      if (!res.is_valid) {
        setCreateModalError(res.message);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Validation request failed";
      setValidationResult({ is_valid: false, message: msg });
      setCreateModalError(msg);
    } finally {
      setIsValidating(false);
    }
  };

  // Initiate OAuth flow
  const handleStartOAuth = async (provider: string) => {
    if (!jwt || !org) return;
    setCreateModalError(null);
    try {
      const res = await getOAuthAuthorizeUrl(provider, jwt, org.org_id);
      window.location.href = res.authorize_url;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to initiate OAuth flow";
      setCreateModalError(msg);
    }
  };

  // Finalize OAuth session
  const handleFinalizeOAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt || !org || !oauthSessionId || !selectedTargetId) return;
    setIsFinalizingOAuth(true);
    setOauthFinalizeError(null);

    try {
      await finalizeOAuthSession(
        oauthSessionId,
        {
          name: newSourceName.trim(),
          target_id: selectedTargetId,
          visibility: newSourceVisibility,
        },
        jwt,
        org.org_id
      );

      setActionSuccess(`Successfully connected ${newSourceName} via OAuth!`);
      setOauthSessionId(null);
      setOauthSessionData(null);
      await fetchSources();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to finalize OAuth connection";
      setOauthFinalizeError(msg);
    } finally {
      setIsFinalizingOAuth(false);
    }
  };

  // Submit Create Source
  const handleCreateSource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt || !org || !isAdmin) return;
    setIsSubmittingCreate(true);
    setCreateModalError(null);

    const config = buildCurrentConfig();
    const credentials = buildCurrentCredentials();
    try {
      await createSource(
        {
          name: newSourceName.trim(),
          type: newSourceType,
          visibility: newSourceVisibility,
          config,
          credentials,
        },
        jwt,
        org.org_id
      );

      setActionSuccess(`Source "${newSourceName.trim()}" created successfully.`);
      setTimeout(() => setActionSuccess(null), 5000);
      resetCreateForm();
      await fetchSources();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create source";
      setCreateModalError(msg);
    } finally {
      setIsSubmittingCreate(false);
    }
  };

  // Trigger Sync
  const handleTriggerSync = async (source: KnowledgeSource) => {
    if (!jwt || !org || !isAdmin) return;
    setGeneralError(null);
    setSyncingSourceIds((prev) => ({ ...prev, [source.id]: true }));

    try {
      const res = await syncSource(source.id, jwt, org.org_id, true);
      setActionSuccess(`Sync initiated for "${source.name}". Status: ${res.status}`);
      setTimeout(() => setActionSuccess(null), 5000);

      // Optimistically set to running in table
      setSources((prev) =>
        prev.map((s) => (s.id === source.id ? { ...s, sync_status: "running" } : s))
      );
    } catch (err: unknown) {
      setSyncingSourceIds((prev) => {
        const next = { ...prev };
        delete next[source.id];
        return next;
      });
      const msg = err instanceof Error ? err.message : "Sync request failed";
      setGeneralError(msg);
    }
  };

  // Toggle Archive
  const handleToggleArchive = async (source: KnowledgeSource) => {
    if (!jwt || !org || !isAdmin) return;
    const actionLabel = source.is_archived ? "restore" : "archive";
    const confirmed = window.confirm(
      `Are you sure you want to ${actionLabel} "${source.name}"? Existing ingested records and citations will remain preserved.`
    );
    if (!confirmed) return;

    try {
      await updateSource(
        source.id,
        { is_archived: !source.is_archived },
        jwt,
        org.org_id
      );
      setActionSuccess(
        `Source "${source.name}" ${source.is_archived ? "restored" : "archived"} successfully.`
      );
      setTimeout(() => setActionSuccess(null), 5000);
      await fetchSources();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : `Failed to ${actionLabel} source`;
      setGeneralError(msg);
    }
  };

  // Permanently Delete Source
  const handleDeleteSource = async (source: KnowledgeSource) => {
    if (!jwt || !org || !isAdmin) return;
    const confirmed = window.confirm(
      `Are you sure you want to permanently delete "${source.name}" and all its records, versions, and embeddings? This action cannot be undone.`
    );
    if (!confirmed) return;

    try {
      await deleteSource(source.id, jwt, org.org_id);
      setActionSuccess(`Source "${source.name}" was permanently deleted.`);
      setTimeout(() => setActionSuccess(null), 5000);
      await fetchSources();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete source";
      setGeneralError(msg);
    }
  };

  // Open Records Modal
  const handleOpenRecords = async (source: KnowledgeSource, offset = 0) => {
    if (!jwt || !org) return;
    setInspectSource(source);
    setRecordsOffset(offset);
    setIsLoadingRecords(true);
    setRecordsError(null);

    try {
      const data = await getSourceRecords(
        source.id,
        jwt,
        org.org_id,
        recordsLimit,
        offset
      );
      setRecordsData(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load source records";
      setRecordsError(msg);
    } finally {
      setIsLoadingRecords(false);
    }
  };

  // Filter sources
  const filteredSources = useMemo(() => {
    return sources.filter((s) => {
      if (!showArchived && s.is_archived) return false;
      if (showArchived && !s.is_archived) return false;
      if (typeFilter !== "all" && s.type !== typeFilter) return false;
      return true;
    });
  }, [sources, typeFilter, showArchived]);

  const renderTypeIcon = (type: SourceType, sizeClass = "w-4 h-4") => {
    return <BrandLogo type={type} className={sizeClass} />;
  };

  const renderStatusBadge = (status: KnowledgeSource["sync_status"], sourceId: string) => {
    const isLocalRunning = syncingSourceIds[sourceId] || status === "running";

    if (isLocalRunning) {
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200">
          <Loader2 className="w-3 h-3 animate-spin" />
          <span>Syncing</span>
        </span>
      );
    }
    if (status === "ok") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
          <CheckCircle2 className="w-3 h-3" />
          <span>Operational</span>
        </span>
      );
    }
    if (status === "partial") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-50 text-amber-800 border border-amber-200">
          <Info className="w-3 h-3" />
          <span>Partial</span>
        </span>
      );
    }
    if (status === "failed") {
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-50 text-rose-700 border border-rose-200">
          <AlertCircle className="w-3 h-3" />
          <span>Sync Failed</span>
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-neutral-100 text-neutral-600">
        <span>Configured</span>
      </span>
    );
  };

  return (
    <div className="flex h-screen bg-[#fcfcfc] text-neutral-900 font-sans antialiased overflow-hidden">
      {/* Navigation Sidebar */}
      <AppSidebar
        currentPath="/sources"
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        apiOnline={apiOnline}
        org={org}
        user={user}
        onSignOut={handleSignOut}
        onSignIn={() => setIsAuthModalOpen(true)}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        <AppHeader
          user={user}
          org={org}
          onOpenSidebar={() => setIsSidebarOpen(true)}
          onSignIn={() => setIsAuthModalOpen(true)}
          onSignOut={handleSignOut}
        />

        <main className="flex-1 max-w-6xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
          {/* Header Title & Action */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-neutral-200/80 pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-neutral-900 flex items-center gap-2">
                <Database className="w-5 h-5 text-neutral-700" />
                <span>Knowledge Sources</span>
              </h1>
              <p className="text-xs text-neutral-500 mt-1">
                Configure and synchronize institutional knowledge connectors under organization tenant isolation.
              </p>
            </div>

            {/* Action Buttons */}
            {jwt && org && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={fetchSources}
                  disabled={isLoadingSources}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-neutral-200 hover:bg-neutral-50 text-neutral-700 rounded-lg text-xs font-medium transition-colors shadow-xs"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isLoadingSources ? "animate-spin" : ""}`} />
                  <span>Refresh</span>
                </button>

                {isAdmin ? (
                  <button
                    type="button"
                    onClick={() => setIsCreateModalOpen(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800 transition-colors shadow-xs"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Connect Source</span>
                  </button>
                ) : (
                  <span
                    title="Only organization administrators can configure sources or initiate ingestion syncs."
                    className="inline-flex items-center gap-1 px-3 py-1.5 bg-neutral-100 text-neutral-400 rounded-lg text-xs font-medium cursor-not-allowed"
                  >
                    <Lock className="w-3.5 h-3.5" />
                    <span>Connect Source (Admin Only)</span>
                  </span>
                )}
              </div>
            )}
          </div>

          {/* Member Mode Notification Banner */}
          {jwt && org && !isAdmin && (
            <div className="rounded-lg bg-blue-50/60 border border-blue-200 p-3 text-xs text-blue-900 flex items-start gap-2.5">
              <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Viewing in Member Mode.</span> You have read-only access to inspect configured sources and evidence records accessible to you under PostgreSQL Row-Level Security. Adding new sources or triggering manual syncs requires organization administrator permissions.
              </div>
            </div>
          )}

          {/* General Error Banner */}
          {generalError && (
            <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{generalError}</span>
              </div>
              <button
                type="button"
                onClick={() => setGeneralError(null)}
                className="text-rose-500 hover:text-rose-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Success Banner */}
          {actionSuccess && (
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{actionSuccess}</span>
            </div>
          )}

          {/* OAuth Error Banner */}
          {oauthError && (
            <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span><strong>OAuth Authorization Error:</strong> {oauthError}</span>
              </div>
              <button
                type="button"
                onClick={() => setOauthError(null)}
                className="text-rose-500 hover:text-rose-700"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Unauthenticated State */}
          {!jwt && !isAuthLoading && (
            <div className="rounded-xl border border-neutral-200 bg-neutral-50/70 p-8 text-center space-y-3">
              <Shield className="w-8 h-8 text-neutral-400 mx-auto" />
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-neutral-800">
                  Authentication Required
                </h3>
                <p className="text-xs text-neutral-500 max-w-sm mx-auto">
                  Sign in with your organization account to view configured knowledge sources and manage connectors.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsAuthModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-4 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800"
              >
                <span>Sign in</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Missing Organization State */}
          {jwt && !org && !isAuthLoading && (
            <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-6 text-center space-y-3">
              <ShieldAlert className="w-8 h-8 text-amber-500 mx-auto" />
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-amber-900">
                  No Active Organization Membership
                </h3>
                <p className="text-xs text-amber-700 max-w-md mx-auto">
                  Signed in as <span className="font-medium font-mono">{user?.email}</span>, but your account is not yet assigned to an organization.
                </p>
                <p className="text-[11px] text-amber-600 max-w-md mx-auto">
                  Run the owner bootstrap script to establish membership:
                </p>
                <code className="inline-block mt-2 px-3 py-1.5 rounded bg-amber-100/90 font-mono text-[11px] text-amber-950 border border-amber-200 select-all">
                  python -m apps.api.scripts.bootstrap_owner --email {user?.email || "owner@institutional-memory.local"}
                </code>
              </div>
              <div className="pt-2">
                <button
                  type="button"
                  onClick={refreshSession}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-amber-200 hover:bg-amber-300 text-amber-950 rounded-lg text-xs font-medium transition-colors"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Refresh Membership</span>
                </button>
              </div>
            </div>
          )}

          {/* Sources List View */}
          {jwt && org && (
            <div className="space-y-6">
              {/* Interactive Integrations Hub Summary */}
              {!showArchived && (
                <div className="space-y-2">
                  <span className="text-[11px] font-semibold text-neutral-400 uppercase tracking-wider block">
                    Integrated Knowledge Ecosystem
                  </span>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    {/* GitHub Card */}
                    <div
                      onClick={() => setTypeFilter(typeFilter === "github" ? "all" : "github")}
                      className={`cursor-pointer rounded-xl border p-4 bg-white shadow-2xs hover:shadow-xs transition-all duration-150 flex items-center justify-between ${
                        typeFilter === "github" ? "border-neutral-900 ring-1 ring-neutral-900" : "border-neutral-200/80 hover:border-neutral-300"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-neutral-900 text-white flex items-center justify-center shadow-2xs shrink-0">
                          <GitHubLogo className="w-5 h-5 text-white" />
                        </div>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-semibold text-neutral-900">GitHub</span>
                            <span className="w-2 h-2 rounded-full bg-emerald-500" title="Connected" />
                          </div>
                          <p className="text-[11.5px] text-neutral-500 font-mono">
                            {sources.filter(s => s.type === "github" && !s.is_archived).reduce((acc, s) => acc + (s.record_count || 0), 0)} records
                          </p>
                        </div>
                      </div>
                      <span className="text-xs font-medium text-neutral-400 font-mono">
                        {sources.filter(s => s.type === "github" && !s.is_archived).length} conn
                      </span>
                    </div>

                    {/* Jira Card */}
                    <div
                      onClick={() => setTypeFilter(typeFilter === "jira" ? "all" : "jira")}
                      className={`cursor-pointer rounded-xl border p-4 bg-white shadow-2xs hover:shadow-xs transition-all duration-150 flex items-center justify-between ${
                        typeFilter === "jira" ? "border-blue-600 ring-1 ring-blue-600" : "border-neutral-200/80 hover:border-neutral-300"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-blue-50 border border-blue-200/80 flex items-center justify-center shadow-2xs shrink-0">
                          <JiraLogo className="w-5 h-5" />
                        </div>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-semibold text-neutral-900">Jira Cloud</span>
                            <span className="w-2 h-2 rounded-full bg-emerald-500" title="Connected" />
                          </div>
                          <p className="text-[11.5px] text-neutral-500 font-mono">
                            {sources.filter(s => s.type === "jira" && !s.is_archived).reduce((acc, s) => acc + (s.record_count || 0), 0)} tickets
                          </p>
                        </div>
                      </div>
                      <span className="text-xs font-medium text-neutral-400 font-mono">
                        {sources.filter(s => s.type === "jira" && !s.is_archived).length} conn
                      </span>
                    </div>

                    {/* Slack Card */}
                    <div
                      onClick={() => setTypeFilter(typeFilter === "slack" ? "all" : "slack")}
                      className={`cursor-pointer rounded-xl border p-4 bg-white shadow-2xs hover:shadow-xs transition-all duration-150 flex items-center justify-between ${
                        typeFilter === "slack" ? "border-emerald-600 ring-1 ring-emerald-600" : "border-neutral-200/80 hover:border-neutral-300"
                      }`}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-emerald-50/70 border border-emerald-200/80 flex items-center justify-center shadow-2xs shrink-0">
                          <SlackLogo className="w-5 h-5" />
                        </div>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-xs font-semibold text-neutral-900">Slack</span>
                            <span className="w-2 h-2 rounded-full bg-emerald-500" title="Connected" />
                          </div>
                          <p className="text-[11.5px] text-neutral-500 font-mono">
                            {sources.filter(s => s.type === "slack" && !s.is_archived).reduce((acc, s) => acc + (s.record_count || 0), 0)} messages
                          </p>
                        </div>
                      </div>
                      <span className="text-xs font-medium text-neutral-400 font-mono">
                        {sources.filter(s => s.type === "slack" && !s.is_archived).length} conn
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* Filter and Tab Controls */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-200 pb-3 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-neutral-500 font-medium">Filter by tool:</span>
                  {(["all", "github", "jira", "slack"] as const).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTypeFilter(t)}
                      className={`px-3 py-1 rounded-lg capitalize font-medium transition-all flex items-center gap-1.5 ${
                        typeFilter === t
                          ? "bg-neutral-900 text-white shadow-2xs"
                          : "bg-white text-neutral-600 border border-neutral-200 hover:bg-neutral-50"
                      }`}
                    >
                      {t !== "all" && <BrandLogo type={t} className="w-3.5 h-3.5" />}
                      <span>{t}</span>
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setShowArchived(!showArchived)}
                    className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                      showArchived
                        ? "bg-amber-100 text-amber-900 border border-amber-300"
                        : "bg-white text-neutral-600 border border-neutral-200 hover:bg-neutral-50"
                    }`}
                  >
                    <Archive className="w-3 h-3" />
                    <span>{showArchived ? "Viewing Archived" : "Show Archived"}</span>
                  </button>
                </div>
              </div>

              {/* Table / Cards */}
              {isLoadingSources && sources.length === 0 ? (
                <div className="py-12 text-center text-xs text-neutral-400">
                  <Loader2 className="w-5 h-5 animate-spin mx-auto mb-2 text-neutral-400" />
                  Loading configured knowledge sources...
                </div>
              ) : filteredSources.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-neutral-300 p-8 text-center space-y-2 bg-white">
                  <Database className="w-7 h-7 text-neutral-400 mx-auto" />
                  <h3 className="text-sm font-semibold text-neutral-800">
                    {showArchived ? "No archived sources" : "No knowledge sources configured yet"}
                  </h3>
                  <p className="text-xs text-neutral-500 max-w-md mx-auto">
                    {showArchived
                      ? "Archived sources will appear here with historical records intact."
                      : "Connect your GitHub repositories, Jira projects, or Slack channels to begin ingesting institutional memory."}
                  </p>
                  {!showArchived && isAdmin && (
                    <div className="pt-2">
                      <button
                        type="button"
                        onClick={() => setIsCreateModalOpen(true)}
                        className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800"
                      >
                        <Plus className="w-3.5 h-3.5" />
                        <span>Connect Your First Source</span>
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div className="grid gap-3.5">
                  {filteredSources.map((source) => {
                    const isLocalSyncing = syncingSourceIds[source.id] || source.sync_status === "running";

                    return (
                      <div
                        key={source.id}
                        className={`rounded-2xl border bg-white p-5 shadow-2xs hover:shadow-xs transition-all duration-150 space-y-3.5 ${
                          source.is_archived
                            ? "border-neutral-200 bg-neutral-50/70 opacity-80"
                            : "border-neutral-200/90 hover:border-neutral-300"
                        }`}
                      >
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                          {/* Left: Brand Icon + Title and metadata */}
                          <div className="flex items-start gap-3.5 min-w-0">
                            {/* Provider Icon Avatar */}
                            <div className="shrink-0 mt-0.5">
                              {source.type === "github" ? (
                                <div className="w-10 h-10 rounded-xl bg-neutral-900 text-white flex items-center justify-center shadow-xs">
                                  <GitHubLogo className="w-5 h-5 text-white" />
                                </div>
                              ) : source.type === "jira" ? (
                                <div className="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200/80 flex items-center justify-center shadow-xs">
                                  <JiraLogo className="w-5 h-5" />
                                </div>
                              ) : source.type === "slack" ? (
                                <div className="w-10 h-10 rounded-xl bg-emerald-50/80 border border-emerald-200/80 flex items-center justify-center shadow-xs">
                                  <SlackLogo className="w-5 h-5" />
                                </div>
                              ) : (
                                <div className="w-10 h-10 rounded-xl bg-neutral-100 border border-neutral-200 flex items-center justify-center shadow-xs">
                                  <Database className="w-5 h-5 text-neutral-600" />
                                </div>
                              )}
                            </div>

                            <div className="space-y-1.5 min-w-0">
                              <div className="flex items-center gap-2 flex-wrap">
                                <h2 className="text-[14.5px] font-semibold text-neutral-900 truncate">
                                  {source.name}
                                </h2>
                                <span className="uppercase text-[10px] font-mono px-2 py-0.5 rounded-md bg-neutral-100 text-neutral-700 font-semibold border border-neutral-200/60">
                                  {source.type}
                                </span>
                                <span
                                  className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${
                                    source.visibility === "restricted"
                                      ? "bg-purple-50 text-purple-700 border-purple-200"
                                      : "bg-neutral-50 text-neutral-600 border-neutral-200"
                                  }`}
                                >
                                  {source.visibility === "restricted" ? "Admin Restricted" : "Public to Org"}
                                </span>
                                {source.has_encrypted_credentials ? (
                                  <span
                                    className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200"
                                    title="Protected with AES-256-GCM organization encryption"
                                  >
                                    <Lock className="w-2.5 h-2.5" />
                                    <span>Org Encrypted</span>
                                  </span>
                                ) : (
                                  <span
                                    className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full border bg-neutral-100 text-neutral-600 border-neutral-200"
                                    title="Using server environment fallback credentials"
                                  >
                                    <span>Server Default</span>
                                  </span>
                                )}
                                {source.is_archived && (
                                  <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-neutral-200 text-neutral-700">
                                    Archived
                                  </span>
                                )}
                              </div>

                              {/* Details: Config & Sync info */}
                              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-neutral-500 font-mono">
                                {source.type === "github" && Boolean(source.config?.repo) && (
                                  <a
                                    href={`https://github.com/${String(source.config.repo)}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-neutral-700 hover:text-blue-600 transition-colors"
                                  >
                                    <span>repo: {String(source.config.repo)}</span>
                                    <ExternalLink className="w-2.5 h-2.5" />
                                  </a>
                                )}
                                {source.type === "jira" && Boolean(source.config?.project) && (
                                  <span className="text-neutral-700">
                                    project: <strong>{String(source.config.project)}</strong> ({String(source.config.base_url || "").replace(/^https?:\/\//, "")})
                                  </span>
                                )}
                                {source.type === "slack" && Boolean(source.config?.channel_id) && (
                                  <span className="text-neutral-700">
                                    channel: <strong>{String(source.config.channel_id)}</strong>
                                  </span>
                                )}
                                <span className="flex items-center gap-1 font-sans text-neutral-400">
                                  <Clock className="w-3 h-3" />
                                  {source.last_synced_at
                                    ? `Synced ${new Date(source.last_synced_at).toLocaleString()}`
                                    : "Never synced"}
                                </span>
                              </div>
                            </div>
                          </div>

                          {/* Right: Record count, Status Badge & Actions */}
                          <div className="flex items-center gap-2.5 self-start sm:self-center shrink-0">
                            {/* Record Count Badge */}
                            <div className="px-2.5 py-1 rounded-lg bg-neutral-50 border border-neutral-200/80 text-xs font-sans text-neutral-600">
                              <span>Records: </span>
                              <strong className="text-neutral-900 font-mono">{source.record_count}</strong>
                            </div>

                            {renderStatusBadge(source.sync_status, source.id)}

                            <button
                              type="button"
                              onClick={() => handleOpenRecords(source, 0)}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-neutral-700 bg-white border border-neutral-200 rounded-lg hover:bg-neutral-50 transition-colors shadow-2xs"
                              title="Inspect ingested evidence records"
                            >
                              <Eye className="w-3.5 h-3.5 text-neutral-500" />
                              <span>Records</span>
                            </button>

                            {isAdmin && !source.is_archived && (
                              <button
                                type="button"
                                onClick={() => handleTriggerSync(source)}
                                disabled={isLocalSyncing}
                                className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors shadow-2xs ${
                                  isLocalSyncing
                                    ? "bg-neutral-100 text-neutral-400 cursor-not-allowed border border-neutral-200"
                                    : "bg-neutral-900 text-white hover:bg-neutral-800"
                                }`}
                                title="Run sync in background"
                              >
                                <RefreshCw className={`w-3.5 h-3.5 ${isLocalSyncing ? "animate-spin" : ""}`} />
                                <span>Sync Now</span>
                              </button>
                            )}

                            {isAdmin && (
                              <button
                                type="button"
                                onClick={() => handleToggleArchive(source)}
                                className="inline-flex items-center gap-1 p-1.5 text-neutral-400 hover:text-neutral-700 hover:bg-neutral-100 rounded-lg transition-colors"
                                title={source.is_archived ? "Restore source" : "Soft-archive source"}
                              >
                                <Archive className="w-3.5 h-3.5" />
                              </button>
                            )}

                            {isAdmin && (
                              <button
                                type="button"
                                onClick={() => handleDeleteSource(source)}
                                className="inline-flex items-center gap-1 p-1.5 text-neutral-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors"
                                title="Permanently delete source and data"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            )}
                          </div>
                        </div>

                        {/* Error Callout if failed */}
                        {source.sync_status === "failed" && source.error_message && (
                          <div className="rounded-lg bg-rose-50/80 border border-rose-200 p-2.5 text-xs text-rose-800 flex items-start gap-2">
                            <AlertCircle className="w-3.5 h-3.5 text-rose-600 shrink-0 mt-0.5" />
                            <div className="overflow-hidden">
                              <span className="font-semibold">Last sync failure: </span>
                              <span className="font-mono text-[11px] break-all">{source.error_message}</span>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* ------------------------------------------------------------------- */}
      {/* CONNECT SOURCE MODAL */}
      {/* ------------------------------------------------------------------- */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="relative w-full max-w-lg bg-white rounded-xl shadow-xl border border-neutral-200 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-base font-bold text-neutral-900">Connect Knowledge Source</h2>
                <p className="text-xs text-neutral-500 mt-0.5">
                  Configure upstream repositories or channels for automated ingestion.
                </p>
              </div>
              <button
                type="button"
                onClick={resetCreateForm}
                className="text-neutral-400 hover:text-neutral-600 rounded-lg p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Connection Method Tabs */}
            <div className="flex border-b border-neutral-200">
              <button
                type="button"
                onClick={() => setConnectionMethod("token")}
                className={`flex-1 py-2 text-xs font-semibold border-b-2 transition-colors ${
                  connectionMethod === "token"
                    ? "border-neutral-900 text-neutral-900"
                    : "border-transparent text-neutral-500 hover:text-neutral-700"
                }`}
              >
                Organization Credentials
              </button>
              <button
                type="button"
                onClick={() => setConnectionMethod("oauth")}
                className={`flex-1 py-2 text-xs font-semibold border-b-2 transition-colors ${
                  connectionMethod === "oauth"
                    ? "border-neutral-900 text-neutral-900"
                    : "border-transparent text-neutral-500 hover:text-neutral-700"
                }`}
              >
                OAuth Authorization
              </button>
            </div>

            {createModalError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-700 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span className="break-all">{createModalError}</span>
              </div>
            )}

            {validationResult && validationResult.is_valid && (
              <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-2.5 text-xs text-emerald-800 flex items-center gap-2">
                <Check className="w-4 h-4 text-emerald-600 shrink-0" />
                <span>{validationResult.message}</span>
              </div>
            )}

            {/* Type Selector (Common for both) */}
            <div className="space-y-1">
              <label className="text-xs font-semibold text-neutral-700 block">
                Connector Provider *
              </label>
              <div className="grid grid-cols-3 gap-2">
                {(["github", "jira", "slack"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => {
                      setNewSourceType(t);
                      setValidationResult(null);
                      setCreateModalError(null);
                    }}
                    className={`px-3 py-2 rounded-lg text-xs font-medium capitalize border transition-all flex items-center justify-center gap-1.5 ${
                      newSourceType === t
                        ? "bg-neutral-900 text-white border-neutral-900 shadow-xs"
                        : "bg-white text-neutral-700 border-neutral-200 hover:bg-neutral-50"
                    }`}
                  >
                    {renderTypeIcon(t)}
                    <span>{t}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* OAuth Flow Mode */}
            {connectionMethod === "oauth" && (() => {
              const prov = oauthStatus?.providers[newSourceType];
              const isAvail = prov?.available;
              return (
                <div className="space-y-4 py-1">
                  <div className="rounded-lg bg-neutral-50 border border-neutral-200 p-3.5 space-y-2">
                    <div className="flex items-center gap-2">
                      {renderTypeIcon(newSourceType)}
                      <span className="text-xs font-semibold text-neutral-900 capitalize">
                        {newSourceType} Multi-Tenant OAuth
                      </span>
                      {isAvail ? (
                        <span className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">
                          Ready to Connect
                        </span>
                      ) : (
                        <span className="ml-auto px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-800 border border-amber-200">
                          Server Setup Required
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-neutral-600 leading-relaxed">
                      {newSourceType === "github" && "Authorizes repository access via GitHub OAuth App or GitHub App. Redirects to GitHub to grant access."}
                      {newSourceType === "jira" && "Authorizes Jira Cloud access via Atlassian OAuth 2.0 (3LO) with offline refresh token capability."}
                      {newSourceType === "slack" && "Authorizes channel history and discussion ingestion via Slack OAuth App installation."}
                    </p>

                    {!isAvail && prov && prov.missing_env_vars.length > 0 && (
                      <div className="rounded bg-amber-50/80 border border-amber-200/80 p-2.5 text-[11px] text-amber-800 space-y-1">
                        <div className="font-semibold flex items-center gap-1.5">
                          <AlertCircle className="w-3.5 h-3.5" />
                          <span>Missing Developer Environment Variables:</span>
                        </div>
                        <div className="font-mono text-[10px] pl-5 space-y-0.5">
                          {prov.missing_env_vars.map((v) => (
                            <div key={v}>• {v}</div>
                          ))}
                        </div>
                        <p className="text-[10px] text-amber-700 mt-1 pl-5">
                          To enable 1-click OAuth, configure these variables in the server environment. Alternatively, switch to the &quot;Organization Credentials&quot; tab to connect immediately using an encrypted token.
                        </p>
                      </div>
                    )}
                  </div>

                  <div className="pt-2 flex items-center justify-end gap-2 border-t border-neutral-100">
                    <button
                      type="button"
                      onClick={resetCreateForm}
                      className="px-3 py-2 text-xs font-medium text-neutral-600 hover:text-neutral-800"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => handleStartOAuth(newSourceType)}
                      disabled={!isAvail}
                      className="inline-flex items-center gap-1.5 px-4 py-2 bg-neutral-900 hover:bg-neutral-800 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-40 shadow-xs"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      <span>Authorize with {newSourceType === "github" ? "GitHub" : newSourceType === "jira" ? "Atlassian" : "Slack"}</span>
                    </button>
                  </div>
                </div>
              );
            })()}

            {/* Direct Token / Credentials Form Mode */}
            {connectionMethod === "token" && (
              <form onSubmit={handleCreateSource} className="space-y-4">
                {/* Security Callout */}
                <div className="rounded-lg bg-neutral-50 border border-neutral-200 p-2.5 text-xs text-neutral-700 space-y-1">
                  <div className="flex items-center gap-1.5 font-semibold text-neutral-900">
                    <Shield className="w-3.5 h-3.5 text-neutral-600" />
                    <span>AES-256-GCM Tenant-Bound Encryption</span>
                  </div>
                  <p className="text-[11px] text-neutral-500 leading-relaxed">
                    Credentials are encrypted server-side with AES-256-GCM bound to your organization ID. They are never returned in plaintext to the browser.
                  </p>
                </div>

                {/* Name */}
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-neutral-700 block">
                    Source Display Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={newSourceName}
                    onChange={(e) => setNewSourceName(e.target.value)}
                    placeholder="e.g. Core Backend Repository"
                    className="w-full px-3 py-2 text-xs border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                  />
                </div>

                {/* Dynamic Type Config Inputs */}
                {newSourceType === "github" && (
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-neutral-700 block">
                        GitHub Repository (<code className="font-mono">owner/repo</code>) *
                      </label>
                      <input
                        type="text"
                        required
                        value={githubRepo}
                        onChange={(e) => {
                          setGithubRepo(e.target.value);
                          setValidationResult(null);
                        }}
                        placeholder="e.g. facebook/react or vercel/next.js"
                        className="w-full px-3 py-2 text-xs font-mono border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-neutral-700 block">
                        GitHub Personal Access Token (PAT) <span className="font-normal text-neutral-400">(Optional)</span>
                      </label>
                      <input
                        type="password"
                        value={githubToken}
                        onChange={(e) => {
                          setGithubToken(e.target.value);
                          setValidationResult(null);
                        }}
                        placeholder="ghp_... or github_pat_..."
                        className="w-full px-3 py-2 text-xs font-mono border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                      />
                      <span className="text-[10px] text-neutral-400 block">
                        If provided, encrypted at rest for this organization. If omitted, uses server fallback.
                      </span>
                    </div>
                  </div>
                )}

                {newSourceType === "jira" && (
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-neutral-700 block">
                        Jira Base URL *
                      </label>
                      <input
                        type="url"
                        required
                        value={jiraBaseUrl}
                        onChange={(e) => {
                          setJiraBaseUrl(e.target.value);
                          setValidationResult(null);
                        }}
                        placeholder="https://your-company.atlassian.net"
                        className="w-full px-3 py-2 text-xs font-mono border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-neutral-700 block">
                        Project Key *
                      </label>
                      <input
                        type="text"
                        required
                        value={jiraProjectKey}
                        onChange={(e) => {
                          setJiraProjectKey(e.target.value);
                          setValidationResult(null);
                        }}
                        placeholder="e.g. ENG or CORE"
                        className="w-full px-3 py-2 text-xs font-mono uppercase border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="space-y-1">
                        <label className="text-xs font-semibold text-neutral-700 block">
                          Atlassian Email <span className="font-normal text-neutral-400">(Optional)</span>
                        </label>
                        <input
                          type="email"
                          value={jiraEmail}
                          onChange={(e) => {
                            setJiraEmail(e.target.value);
                            setValidationResult(null);
                          }}
                          placeholder="admin@company.com"
                          className="w-full px-3 py-2 text-xs border border-neutral-300 rounded-lg focus:ring-2 focus:ring-neutral-900"
                        />
                      </div>
                      <div className="space-y-1">
                        <label className="text-xs font-semibold text-neutral-700 block">
                          API Token <span className="font-normal text-neutral-400">(Optional)</span>
                        </label>
                        <input
                          type="password"
                          value={jiraToken}
                          onChange={(e) => {
                            setJiraToken(e.target.value);
                            setValidationResult(null);
                          }}
                          placeholder="ATATT3xFf..."
                          className="w-full px-3 py-2 text-xs font-mono border border-neutral-300 rounded-lg focus:ring-2 focus:ring-neutral-900"
                        />
                      </div>
                    </div>
                  </div>
                )}

                {newSourceType === "slack" && (
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-neutral-700 block">
                        Slack Channel ID *
                      </label>
                      <input
                        type="text"
                        required
                        value={slackChannelId}
                        onChange={(e) => {
                          setSlackChannelId(e.target.value);
                          setValidationResult(null);
                        }}
                        placeholder="e.g. C0123456789"
                        className="w-full px-3 py-2 text-xs font-mono uppercase border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                      />
                      <span className="text-[10px] text-neutral-400 block">
                        Channel ID starting with &apos;C&apos;. Bot must be invited to channel.
                      </span>
                    </div>
                    <div className="space-y-1">
                      <label className="text-xs font-semibold text-neutral-700 block">
                        Slack Bot Token <span className="font-normal text-neutral-400">(Optional)</span>
                      </label>
                      <input
                        type="password"
                        value={slackToken}
                        onChange={(e) => {
                          setSlackToken(e.target.value);
                          setValidationResult(null);
                        }}
                        placeholder="xoxb-..."
                        className="w-full px-3 py-2 text-xs font-mono border border-neutral-300 rounded-lg focus:outline-hidden focus:ring-2 focus:ring-neutral-900 focus:border-transparent"
                      />
                      <span className="text-[10px] text-neutral-400 block">
                        Encrypted server-side for this organization. If omitted, uses server fallback.
                      </span>
                    </div>
                  </div>
                )}

                {/* Visibility */}
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-neutral-700 block">
                    Visibility & Access Control *
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setNewSourceVisibility("public")}
                      className={`p-2.5 rounded-lg border text-left text-xs transition-colors ${
                        newSourceVisibility === "public"
                          ? "border-neutral-900 bg-neutral-50 ring-1 ring-neutral-900"
                          : "border-neutral-200 hover:bg-neutral-50"
                      }`}
                    >
                      <div className="font-semibold text-neutral-900">Public to Org</div>
                      <div className="text-[11px] text-neutral-500 mt-0.5">
                        All organization members can query records from this source.
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setNewSourceVisibility("restricted")}
                      className={`p-2.5 rounded-lg border text-left text-xs transition-colors ${
                        newSourceVisibility === "restricted"
                          ? "border-purple-600 bg-purple-50/60 ring-1 ring-purple-600"
                          : "border-neutral-200 hover:bg-neutral-50"
                      }`}
                    >
                      <div className="font-semibold text-purple-900">Admin Restricted</div>
                      <div className="text-[11px] text-purple-700 mt-0.5">
                        Only organization admins can query or view records.
                      </div>
                    </button>
                  </div>
                </div>

                {/* Action Buttons */}
                <div className="pt-2 flex items-center justify-between gap-2 border-t border-neutral-100">
                  <button
                    type="button"
                    onClick={handleValidateConfig}
                    disabled={isValidating || !newSourceName}
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-neutral-700 bg-neutral-100 hover:bg-neutral-200 rounded-lg transition-colors disabled:opacity-50"
                  >
                    {isValidating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    <span>Test Connection</span>
                  </button>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={resetCreateForm}
                      className="px-3 py-2 text-xs font-medium text-neutral-600 hover:text-neutral-800"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={isSubmittingCreate || !newSourceName}
                      className="inline-flex items-center gap-1.5 px-4 py-2 bg-neutral-900 hover:bg-neutral-800 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
                    >
                      {isSubmittingCreate && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                      <span>Connect Source</span>
                    </button>
                  </div>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------- */}
      {/* OAUTH COMPLETE SETUP MODAL */}
      {/* ------------------------------------------------------------------- */}
      {oauthSessionData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="relative w-full max-w-lg bg-white rounded-xl shadow-xl border border-neutral-200 p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-1.5 text-xs text-emerald-600 font-semibold mb-1">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>OAuth Authorization Successful</span>
                </div>
                <h2 className="text-base font-bold text-neutral-900">
                  Select {oauthSessionData.provider === "github" ? "Repository" : oauthSessionData.provider === "jira" ? "Atlassian Site" : "Slack Channel"}
                </h2>
                <p className="text-xs text-neutral-500 mt-0.5">
                  Authenticated as <strong className="text-neutral-800">{oauthSessionData.account_name}</strong>. Choose an entity to ingest.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOauthSessionData(null)}
                className="text-neutral-400 hover:text-neutral-600 rounded-lg p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {oauthFinalizeError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-700 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span className="break-all">{oauthFinalizeError}</span>
              </div>
            )}

            <form onSubmit={handleFinalizeOAuth} className="space-y-4">
              {/* Target Selector */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-neutral-700 block">
                  Available {oauthSessionData.provider === "github" ? "Repositories" : oauthSessionData.provider === "jira" ? "Sites" : "Channels"} *
                </label>
                {oauthSessionData.targets.length === 0 ? (
                  <div className="text-xs text-neutral-500 p-3 bg-neutral-50 rounded-lg border border-neutral-200">
                    No accessible entities found for this account.
                  </div>
                ) : (
                  <div className="max-h-48 overflow-y-auto space-y-1.5 border border-neutral-200 rounded-lg p-2">
                    {oauthSessionData.targets.map((target) => (
                      <label
                        key={target.id}
                        className={`flex items-center justify-between p-2 rounded-md border text-xs cursor-pointer transition-colors ${
                          selectedTargetId === target.id
                            ? "border-neutral-900 bg-neutral-50 ring-1 ring-neutral-900"
                            : "border-neutral-100 hover:bg-neutral-50"
                        }`}
                      >
                        <div className="flex items-center gap-2 overflow-hidden">
                          <input
                            type="radio"
                            name="oauth_target"
                            value={target.id}
                            checked={selectedTargetId === target.id}
                            onChange={() => {
                              setSelectedTargetId(target.id);
                              setNewSourceName(`${target.name} (${oauthSessionData.account_name})`);
                            }}
                            className="text-neutral-900 focus:ring-neutral-900"
                          />
                          <span className="font-mono text-neutral-900 font-medium truncate">
                            {target.name}
                          </span>
                        </div>
                        {Boolean(target.extra?.private) && (
                          <span className="text-[10px] bg-neutral-200 text-neutral-700 px-1.5 py-0.5 rounded font-medium">
                            Private
                          </span>
                        )}
                      </label>
                    ))}
                  </div>
                )}
              </div>

              {/* Display Name */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-neutral-700 block">
                  Source Display Name *
                </label>
                <input
                  type="text"
                  required
                  value={newSourceName}
                  onChange={(e) => setNewSourceName(e.target.value)}
                  placeholder="e.g. Production Backend"
                  className="w-full px-3 py-2 text-xs border border-neutral-300 rounded-lg focus:ring-2 focus:ring-neutral-900"
                />
              </div>

              {/* Visibility */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-neutral-700 block">
                  Visibility *
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setNewSourceVisibility("public")}
                    className={`p-2 rounded-lg border text-left text-xs transition-colors ${
                      newSourceVisibility === "public"
                        ? "border-neutral-900 bg-neutral-50 ring-1 ring-neutral-900"
                        : "border-neutral-200 hover:bg-neutral-50"
                    }`}
                  >
                    <div className="font-semibold text-neutral-900">Public to Org</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setNewSourceVisibility("restricted")}
                    className={`p-2 rounded-lg border text-left text-xs transition-colors ${
                      newSourceVisibility === "restricted"
                        ? "border-purple-600 bg-purple-50/60 ring-1 ring-purple-600"
                        : "border-neutral-200 hover:bg-neutral-50"
                    }`}
                  >
                    <div className="font-semibold text-purple-900">Admin Restricted</div>
                  </button>
                </div>
              </div>

              {/* Actions */}
              <div className="pt-2 flex items-center justify-end gap-2 border-t border-neutral-100">
                <button
                  type="button"
                  onClick={() => setOauthSessionData(null)}
                  className="px-3 py-2 text-xs font-medium text-neutral-600 hover:text-neutral-800"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isFinalizingOAuth || !selectedTargetId || !newSourceName}
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-neutral-900 hover:bg-neutral-800 text-white rounded-lg text-xs font-medium transition-colors disabled:opacity-50 shadow-xs"
                >
                  {isFinalizingOAuth && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>Add to Knowledge Sources</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------- */}
      {/* VIEW RECORDS MODAL */}
      {/* ------------------------------------------------------------------- */}
      {inspectSource && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
          <div className="relative w-full max-w-4xl bg-white rounded-xl shadow-2xl border border-neutral-200 flex flex-col max-h-[88vh] overflow-hidden">
            {/* Header */}
            <div className="p-4 sm:p-5 border-b border-neutral-200 flex items-start justify-between gap-4 bg-neutral-50/50">
              <div>
                <div className="flex items-center gap-2">
                  <span className="p-1 rounded bg-white border border-neutral-200">
                    {renderTypeIcon(inspectSource.type)}
                  </span>
                  <h2 className="text-base font-bold text-neutral-900">
                    {inspectSource.name}
                  </h2>
                  <span className="text-xs text-neutral-400 font-mono">
                    ({inspectSource.type})
                  </span>
                </div>
                <p className="text-xs text-neutral-500 mt-1">
                  Viewing ingested records and chunk embeddings under organization tenant isolation.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setInspectSource(null)}
                className="text-neutral-400 hover:text-neutral-600 rounded-lg p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Error in Records View */}
            {recordsError && (
              <div className="m-4 rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{recordsError}</span>
              </div>
            )}

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-3">
              {isLoadingRecords ? (
                <div className="py-16 text-center text-xs text-neutral-400">
                  <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-neutral-400" />
                  Loading ingested records...
                </div>
              ) : !recordsData || recordsData.items.length === 0 ? (
                <div className="py-16 text-center space-y-2">
                  <FileText className="w-8 h-8 text-neutral-300 mx-auto" />
                  <h3 className="text-sm font-semibold text-neutral-800">
                    No records found for this source
                  </h3>
                  <p className="text-xs text-neutral-500 max-w-sm mx-auto">
                    Trigger a sync from the Knowledge Sources dashboard to scan and ingest evidence records.
                  </p>
                </div>
              ) : (
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between text-xs text-neutral-500 pb-1">
                    <span>
                      Showing <strong>{recordsOffset + 1}</strong>-
                      <strong>
                        {Math.min(recordsOffset + recordsData.items.length, recordsData.total)}
                      </strong>{" "}
                      of <strong>{recordsData.total}</strong> records
                    </span>
                  </div>

                  <div className="grid gap-2.5">
                    {recordsData.items.map((rec: SourceRecord) => (
                      <div
                        key={rec.id}
                        className="rounded-lg border border-neutral-200 p-3 bg-white space-y-1.5 transition-colors hover:border-neutral-300"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="space-y-0.5">
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-600">
                                {rec.record_type}
                              </span>
                              <h4 className="text-xs font-semibold text-neutral-900">
                                {rec.title || rec.external_id}
                              </h4>
                            </div>
                            <span className="text-[11px] text-neutral-400 font-mono block">
                              ID: {rec.external_id}
                            </span>
                          </div>

                          <div className="flex items-center gap-2 shrink-0 text-[11px] text-neutral-400">
                            {rec.chunk_count > 0 && (
                              <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 font-mono text-[10px]">
                                {rec.chunk_count} chunk{rec.chunk_count > 1 ? "s" : ""}
                              </span>
                            )}
                            {rec.url && (
                              <a
                                href={rec.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-neutral-500 hover:text-neutral-800 p-1"
                                title="Open upstream record"
                              >
                                <ExternalLink className="w-3.5 h-3.5" />
                              </a>
                            )}
                          </div>
                        </div>

                        {rec.snippet && (
                          <p className="text-xs text-neutral-600 line-clamp-2 bg-neutral-50/70 p-2 rounded border border-neutral-100 font-sans leading-relaxed">
                            {rec.snippet}
                          </p>
                        )}

                        <div className="flex items-center gap-4 text-[10px] text-neutral-400 pt-0.5 font-mono">
                          {rec.author_name && <span>Author: {rec.author_name}</span>}
                          <span>Updated: {new Date(rec.updated_at).toLocaleDateString()}</span>
                          {rec.version_index !== null && rec.version_index !== undefined && (
                            <span>v{rec.version_index}</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Pagination Footer */}
            {recordsData && recordsData.total > recordsLimit && (
              <div className="p-3 sm:px-5 border-t border-neutral-200 bg-neutral-50/50 flex items-center justify-between text-xs">
                <button
                  type="button"
                  onClick={() => handleOpenRecords(inspectSource, Math.max(0, recordsOffset - recordsLimit))}
                  disabled={recordsOffset === 0 || isLoadingRecords}
                  className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-neutral-200 rounded-lg text-neutral-700 hover:bg-neutral-50 disabled:opacity-40 transition-colors"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                  <span>Previous</span>
                </button>

                <span className="text-neutral-500 font-mono text-[11px]">
                  Page {Math.floor(recordsOffset / recordsLimit) + 1} of{" "}
                  {Math.ceil(recordsData.total / recordsLimit)}
                </span>

                <button
                  type="button"
                  onClick={() => handleOpenRecords(inspectSource, recordsOffset + recordsLimit)}
                  disabled={recordsOffset + recordsLimit >= recordsData.total || isLoadingRecords}
                  className="inline-flex items-center gap-1 px-3 py-1.5 bg-white border border-neutral-200 rounded-lg text-neutral-700 hover:bg-neutral-50 disabled:opacity-40 transition-colors"
                >
                  <span>Next</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onSuccess={refreshSession}
      />
    </div>
  );
}

