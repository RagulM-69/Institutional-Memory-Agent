"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  UserCheck,
  Plus,
  Clock,
  AlertTriangle,
  ArrowRight,
  Shield,
  ShieldAlert,
  RefreshCw,
  Lock,
  FileText,
  Calendar,
  User,
  Sparkles,
  Loader2,
  Wand2,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { AuthModal } from "@/components/auth/AuthModal";
import {
  ActiveOrganization,
  AuthenticatedUser,
  DetectedSubjects,
  Handoff,
  HandoffItemStatus,
  HandoffStatus,
  HandoffSubjectType,
  TeamMember,
} from "@/lib/types";
import {
  checkApiHealth,
  getCurrentOrg,
  getCurrentUser,
  listHandoffs,
  getHandoff,
  createHandoff,
  updateHandoff,
  updateHandoffItem,
  listTeamMembers,
  getDetectedSubjects,
  generateHandoff,
  ApiError,
} from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

export default function HandoffsWorkspace() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Handoffs List & Selected Handoff
  const [handoffs, setHandoffs] = useState<Handoff[]>([]);
  const [selectedHandoff, setSelectedHandoff] = useState<Handoff | null>(null);
  const [isLoadingHandoffs, setIsLoadingHandoffs] = useState<boolean>(false);
  const [isLoadingDetail, setIsLoadingDetail] = useState<boolean>(false);
  const [generalError, setGeneralError] = useState<string | null>(null);

  // Create Handoff Modal State
  const [isCreateModalOpen, setIsCreateModalOpen] = useState<boolean>(false);
  const [createTitle, setCreateTitle] = useState<string>("");
  const [createSubjectType, setCreateSubjectType] = useState<HandoffSubjectType>("service");
  const [createSubjectIdentifier, setCreateSubjectIdentifier] = useState<string>("");
  const [createSummary, setCreateSummary] = useState<string>("");
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);

  // Items in creation modal
  const [itemsToCreate, setItemsToCreate] = useState<
    Array<{
      title: string;
      description: string;
      item_status: HandoffItemStatus;
      record_id?: string;
      note_id?: string;
      assignee_user_id?: string;
      due_date?: string;
    }>
  >([]);
  const [newItemTitle, setNewItemTitle] = useState<string>("");
  const [newItemDesc, setNewItemDesc] = useState<string>("");
  const [newItemStatus, setNewItemStatus] = useState<HandoffItemStatus>("verified");
  const [newItemRecordId, setNewItemRecordId] = useState<string>("");
  const [newItemAssignee, setNewItemAssignee] = useState<string>("");
  const [newItemDueDate, setNewItemDueDate] = useState<string>("");

  const [isSubmittingHandoff, setIsSubmittingHandoff] = useState<boolean>(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Auto-Generate Dossier Modal State
  const [isGenerateModalOpen, setIsGenerateModalOpen] = useState<boolean>(false);
  const [generateSubjectType, setGenerateSubjectType] = useState<HandoffSubjectType>("person");
  const [generateSubjectIdentifier, setGenerateSubjectIdentifier] = useState<string>("");
  const [generateRecipientUserId, setGenerateRecipientUserId] = useState<string>("");
  const [detectedSubjects, setDetectedSubjects] = useState<DetectedSubjects | null>(null);
  const [isLoadingDetected, setIsLoadingDetected] = useState<boolean>(false);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

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

  // Load Handoffs list
  const fetchHandoffsList = useCallback(async () => {
    if (!jwt || !org) return;
    setIsLoadingHandoffs(true);
    setGeneralError(null);
    try {
      const data = await listHandoffs(jwt, org?.org_id);
      setHandoffs(data);
    } catch (err: unknown) {
      setGeneralError(err instanceof Error ? err.message : "Failed to load handoffs");
    } finally {
      setIsLoadingHandoffs(false);
    }
  }, [jwt, org]);

  useEffect(() => {
    let cancelled = false;
    async function executeLoad() {
      if (!cancelled && jwt && org) {
        await fetchHandoffsList();
        try {
          const members = await listTeamMembers(jwt, org.org_id);
          if (!cancelled) setTeamMembers(members);
        } catch {
          // ignore directory fetch error for non-admins
        }
      }
    }
    executeLoad();
    return () => {
      cancelled = true;
    };
  }, [jwt, org, fetchHandoffsList]);

  // Load Selected Handoff Details
  const handleSelectHandoff = async (h: Handoff) => {
    if (!jwt) return;
    setIsLoadingDetail(true);
    setGeneralError(null);
    try {
      const detail = await getHandoff(h.id, jwt, org?.org_id);
      setSelectedHandoff(detail);
    } catch (err: unknown) {
      setGeneralError(err instanceof Error ? err.message : "Failed to load handoff details");
    } finally {
      setIsLoadingDetail(false);
    }
  };

  // Update Item Status & Assignee
  const handleUpdateItemStatus = async (itemId: string, newStatus: HandoffItemStatus) => {
    if (!selectedHandoff || !jwt || !org) return;
    try {
      const updated = await updateHandoffItem(
        selectedHandoff.id,
        itemId,
        { item_status: newStatus },
        jwt,
        org.org_id
      );
      setSelectedHandoff((prev) => {
        if (!prev || !prev.items) return prev;
        return {
          ...prev,
          items: prev.items.map((it) => (it.id === itemId ? { ...it, item_status: updated.item_status } : it)),
        };
      });
    } catch (err: unknown) {
      setGeneralError(err instanceof Error ? err.message : "Failed to update item status");
    }
  };

  // Add Item to creation list
  const handleAddItemToForm = () => {
    if (!newItemTitle.trim()) return;
    setItemsToCreate((prev) => [
      ...prev,
      {
        title: newItemTitle.trim(),
        description: newItemDesc.trim(),
        item_status: newItemStatus,
        record_id: newItemRecordId.trim() || undefined,
        assignee_user_id: newItemAssignee.trim() || undefined,
        due_date: newItemDueDate ? new Date(newItemDueDate).toISOString() : undefined,
      },
    ]);
    setNewItemTitle("");
    setNewItemDesc("");
    setNewItemStatus("verified");
    setNewItemRecordId("");
    setNewItemAssignee("");
    setNewItemDueDate("");
  };

  // Submit New Handoff
  const handleCreateHandoff = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt) return;
    setIsSubmittingHandoff(true);
    setCreateError(null);

    try {
      const created = await createHandoff(
        {
          title: createTitle.trim(),
          subject_type: createSubjectType,
          subject_identifier: createSubjectIdentifier.trim(),
          summary: createSummary.trim() || undefined,
          items: itemsToCreate,
        },
        jwt,
        org?.org_id
      );

      setCreateTitle("");
      setCreateSubjectIdentifier("");
      setCreateSummary("");
      setItemsToCreate([]);
      setIsCreateModalOpen(false);
      await fetchHandoffsList();
      setSelectedHandoff(created);
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Failed to create handoff");
    } finally {
      setIsSubmittingHandoff(false);
    }
  };

  // Open Generate Modal & Fetch Auto-Detected Subjects
  const handleOpenGenerateModal = async () => {
    setIsGenerateModalOpen(true);
    setGenerateError(null);
    if (!detectedSubjects && jwt && org) {
      setIsLoadingDetected(true);
      try {
        const detected = await getDetectedSubjects(jwt, org.org_id);
        setDetectedSubjects(detected);
        if (detected.engineers.length > 0 && !generateSubjectIdentifier) {
          setGenerateSubjectIdentifier(detected.engineers[0]);
          setGenerateSubjectType("person");
        }
      } catch {
        // gracefully handle fallback
      } finally {
        setIsLoadingDetected(false);
      }
    }
  };

  // Submit Auto-Generation
  const handleGenerateDossier = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt || !org || !generateSubjectIdentifier.trim()) return;
    setIsGenerating(true);
    setGenerateError(null);

    try {
      const generated = await generateHandoff(
        {
          subject_type: generateSubjectType,
          subject_identifier: generateSubjectIdentifier.trim(),
          recipient_user_id: generateRecipientUserId || undefined,
        },
        jwt,
        org.org_id
      );

      setIsGenerateModalOpen(false);
      await fetchHandoffsList();
      setSelectedHandoff(generated);
    } catch (err: unknown) {
      setGenerateError(
        err instanceof Error ? err.message : "Failed to auto-generate handoff dossier"
      );
    } finally {
      setIsGenerating(false);
    }
  };

  // Update Status
  const handleStatusChange = async (newStatus: HandoffStatus) => {
    if (!selectedHandoff || !jwt) return;
    try {
      const updated = await updateHandoff(
        selectedHandoff.id,
        { status: newStatus },
        jwt,
        org?.org_id
      );
      setSelectedHandoff((prev) => (prev ? { ...prev, status: updated.status } : null));
      await fetchHandoffsList();
    } catch (err: unknown) {
      setGeneralError(err instanceof Error ? err.message : "Failed to update status");
    }
  };

  const renderStatusBadge = (status: HandoffItemStatus) => {
    switch (status) {
      case "verified":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
            Verified
          </span>
        );
      case "inferred":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
            Inferred
          </span>
        );
      case "unresolved":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-800 border border-rose-200">
            Unresolved
          </span>
        );
      case "outdated":
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-neutral-100 text-neutral-600 border border-neutral-200">
            Outdated
          </span>
        );
    }
  };

  return (
    <div className="flex h-screen bg-[#fcfcfc] text-neutral-900 font-sans antialiased overflow-hidden">
      {/* Navigation Sidebar */}
      <AppSidebar
        currentPath="/handoffs"
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
          {/* Header Title & Actions */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-neutral-200/80 pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-neutral-900 flex items-center gap-2">
                <UserCheck className="w-5 h-5 text-neutral-700" />
                <span>Structured Handoffs Workspace</span>
              </h1>
              <p className="text-xs text-neutral-500 mt-1">
                Preserve architecture decisions, dependencies, and open questions during service handoffs or engineer transitions.
              </p>
            </div>

            {jwt && org && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleOpenGenerateModal}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800 transition-all shadow-xs group"
                >
                  <Sparkles className="w-3.5 h-3.5 text-emerald-400 group-hover:rotate-12 transition-transform" />
                  <span>Auto-Generate Dossier</span>
                </button>
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-neutral-300 text-neutral-700 rounded-lg text-xs font-medium hover:bg-neutral-50 transition-colors shadow-xs"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Manual Handoff</span>
                </button>
              </div>
            )}
          </div>

          {/* General Error Banner */}
          {generalError && (
            <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0" />
              <span>{generalError}</span>
            </div>
          )}

          {/* Unauthenticated State */}
          {!jwt && !isAuthLoading && (
            <div className="rounded-xl border border-neutral-200 bg-neutral-50/70 p-6 text-center space-y-3">
              <Shield className="w-8 h-8 text-neutral-400 mx-auto" />
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-neutral-800">
                  Authentication Required
                </h3>
                <p className="text-xs text-neutral-500 max-w-sm mx-auto">
                  Sign in to view or author structured handoffs with tenant isolation.
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

          {/* Handoffs Workspace Grid: Left list, Right detail */}
          {jwt && org && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* Left Column: Handoffs List */}
              <div className="lg:col-span-5 space-y-3">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400 block">
                  Active Handoffs ({handoffs.length})
                </span>

                {isLoadingHandoffs ? (
                  <div className="py-8 text-center text-xs text-neutral-400">
                    Loading handoffs...
                  </div>
                ) : handoffs.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-neutral-300 p-6 text-center space-y-2 bg-white">
                    <UserCheck className="w-6 h-6 text-neutral-400 mx-auto" />
                    <h3 className="text-xs font-semibold text-neutral-800">No handoffs yet</h3>
                    <p className="text-[11px] text-neutral-500">
                      Create a handoff package to track verified knowledge transfer.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {handoffs.map((h) => {
                      const isSelected = selectedHandoff?.id === h.id;
                      return (
                        <div
                          key={h.id}
                          onClick={() => handleSelectHandoff(h)}
                          className={`p-3.5 rounded-xl border text-left cursor-pointer transition-all ${
                            isSelected
                              ? "bg-white border-neutral-900 shadow-xs"
                              : "bg-white border-neutral-200/90 hover:border-neutral-300 shadow-xs"
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-600 font-mono">
                              {h.subject_type}: {h.subject_identifier}
                            </span>
                            <span className="text-[10px] capitalize px-1.5 py-0.5 rounded font-mono border text-neutral-700 bg-neutral-50 border-neutral-200">
                              {h.status}
                            </span>
                          </div>

                          <h2 className="text-xs font-semibold text-neutral-900 mt-2 line-clamp-1">
                            {h.title}
                          </h2>

                          {h.summary && (
                            <p className="text-[11px] text-neutral-500 mt-1 line-clamp-2">
                              {h.summary}
                            </p>
                          )}

                          <div className="flex items-center justify-between mt-3 pt-2 border-t border-neutral-100 text-[10px] text-neutral-400">
                            <span>{h.item_count} transfer items</span>
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {new Date(h.created_at).toLocaleDateString()}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Right Column: Selected Handoff Details */}
              <div className="lg:col-span-7">
                {selectedHandoff ? (
                  <div className="rounded-xl border border-neutral-200 bg-white p-5 shadow-xs space-y-5 animate-in fade-in">
                    {/* Header & Controls */}
                    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 border-b border-neutral-100 pb-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] uppercase font-semibold text-neutral-500 font-mono">
                            Subject: {selectedHandoff.subject_type} / {selectedHandoff.subject_identifier}
                          </span>
                        </div>
                        <h2 className="text-base font-bold text-neutral-900 leading-snug">
                          {selectedHandoff.title}
                        </h2>
                      </div>

                      {/* Status Selector */}
                      <div className="flex items-center gap-1.5 shrink-0">
                        <span className="text-[10px] text-neutral-400 font-medium">Status:</span>
                        <select
                          value={selectedHandoff.status}
                          onChange={(e) => handleStatusChange(e.target.value as HandoffStatus)}
                          className="text-xs px-2 py-1 rounded-md border border-neutral-300 bg-white font-mono"
                        >
                          <option value="draft">draft</option>
                          <option value="reviewed">reviewed</option>
                          <option value="confirmed">confirmed</option>
                          <option value="acknowledged">acknowledged</option>
                          <option value="archived">archived</option>
                        </select>
                      </div>
                    </div>

                    {/* Summary */}
                    {selectedHandoff.summary && (
                      <div className="rounded-lg bg-neutral-50/70 border border-neutral-200/70 p-3 text-xs text-neutral-700 leading-relaxed">
                        <span className="text-[10px] font-semibold uppercase tracking-wider text-neutral-400 block mb-1">
                          Handoff Executive Summary
                        </span>
                        {selectedHandoff.summary}
                      </div>
                    )}

                    {/* Handoff Items List */}
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-neutral-900">
                          Transfer Items ({selectedHandoff.items?.length || 0})
                        </span>
                        <span className="text-[10px] text-neutral-400">
                          Verified against PostgreSQL evidence catalog
                        </span>
                      </div>

                      {isLoadingDetail ? (
                        <div className="py-8 text-center text-xs text-neutral-400">
                          Loading items...
                        </div>
                      ) : !selectedHandoff.items || selectedHandoff.items.length === 0 ? (
                        <div className="text-center py-6 text-xs text-neutral-400">
                          No items attached to this handoff.
                        </div>
                      ) : (
                        <div className="space-y-2.5">
                          {selectedHandoff.items.map((item) => (
                            <div
                              key={item.id}
                              className="rounded-lg border border-neutral-200/80 p-3 space-y-2 bg-white"
                            >
                              <div className="flex items-start justify-between gap-2">
                                <h3 className="text-xs font-semibold text-neutral-900">
                                  {item.title}
                                </h3>
                                {(org?.role === "admin" || org?.role === "team_lead") ? (
                                  <select
                                    value={item.item_status}
                                    onChange={(e) =>
                                      handleUpdateItemStatus(
                                        item.id,
                                        e.target.value as HandoffItemStatus
                                      )
                                    }
                                    className="text-[10px] font-semibold border border-neutral-300 rounded px-1.5 py-0.5 bg-neutral-50 text-neutral-700 hover:bg-neutral-100 cursor-pointer"
                                  >
                                    <option value="verified">Verified</option>
                                    <option value="inferred">Inferred</option>
                                    <option value="unresolved">Unresolved</option>
                                    <option value="outdated">Outdated</option>
                                  </select>
                                ) : (
                                  renderStatusBadge(item.item_status)
                                )}
                              </div>

                              {item.description && (
                                <p className="text-[11.5px] text-neutral-600 leading-relaxed">
                                  {item.description}
                                </p>
                              )}

                              {/* Confidential/Restricted Evidence Notice */}
                              {item.is_restricted_evidence && (
                                <div className="flex items-center gap-1.5 text-[10px] text-amber-700 bg-amber-50/70 border border-amber-200/70 px-2 py-1 rounded">
                                  <Lock className="w-3 h-3 text-amber-600" />
                                  <span>Attached evidence is confidential; details masked for current identity.</span>
                                </div>
                              )}

                              {/* Attached Record Reference */}
                              {item.record_title && !item.is_restricted_evidence && (
                                <div className="flex items-center gap-1.5 text-[11px] text-neutral-600 font-mono bg-neutral-50 px-2 py-0.5 rounded border border-neutral-200/60 w-fit">
                                  <FileText className="w-3 h-3 text-neutral-400" />
                                  <span>Record: {item.record_title}</span>
                                </div>
                              )}

                              {/* Assignee & Due Date Meta */}
                              {(item.assignee_user_id || item.due_date) && (
                                <div className="flex flex-wrap items-center gap-3 pt-1 text-[11px] text-neutral-500 border-t border-neutral-100 mt-1">
                                  {item.assignee_user_id && (
                                    <div className="flex items-center gap-1 font-medium text-neutral-700">
                                      <User className="w-3 h-3 text-neutral-400" />
                                      <span>
                                        {teamMembers.find((m) => m.user_id === item.assignee_user_id)?.email ||
                                          `User: ${item.assignee_user_id.slice(0, 8)}...`}
                                      </span>
                                    </div>
                                  )}
                                  {item.due_date && (
                                    <div className="flex items-center gap-1 text-neutral-600">
                                      <Calendar className="w-3 h-3 text-neutral-400" />
                                      <span>Due {new Date(item.due_date).toLocaleDateString()}</span>
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-neutral-200 p-12 text-center text-neutral-400 bg-white">
                    <UserCheck className="w-8 h-8 mx-auto mb-2 text-neutral-300" />
                    <p className="text-xs">Select a handoff package from the left to view verified items.</p>
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Modal: Create Handoff */}
      {isCreateModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-xl border border-neutral-200 p-6 max-w-xl w-full shadow-lg space-y-4 max-h-[90vh] overflow-y-auto animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-neutral-100 pb-3">
              <h3 className="text-sm font-semibold text-neutral-900 flex items-center gap-2">
                <UserCheck className="w-4 h-4 text-neutral-700" />
                <span>Create Structured Handoff Package</span>
              </h3>
              <button
                type="button"
                onClick={() => setIsCreateModalOpen(false)}
                className="text-neutral-400 hover:text-neutral-600 text-xs font-mono"
              >
                ✕
              </button>
            </div>

            {createError && (
              <div className="p-2.5 rounded bg-rose-50 border border-rose-200 text-xs text-rose-700">
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateHandoff} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">Handoff Title</label>
                <input
                  type="text"
                  required
                  value={createTitle}
                  onChange={(e) => setCreateTitle(e.target.value)}
                  placeholder="e.g. Identity Service Ownership Transition"
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-neutral-700 block">Subject Type</label>
                  <select
                    value={createSubjectType}
                    onChange={(e) => setCreateSubjectType(e.target.value as HandoffSubjectType)}
                    className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-white"
                  >
                    <option value="service">Service</option>
                    <option value="person">Person</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-medium text-neutral-700 block">Subject Identifier</label>
                  <input
                    type="text"
                    required
                    value={createSubjectIdentifier}
                    onChange={(e) => setCreateSubjectIdentifier(e.target.value)}
                    placeholder="e.g. identity-svc or engineer@acme.corp"
                    className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">Executive Summary</label>
                <textarea
                  rows={3}
                  value={createSummary}
                  onChange={(e) => setCreateSummary(e.target.value)}
                  placeholder="Overview of scope, critical services, and handoff goals..."
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900 font-sans"
                />
              </div>

              {/* Items Section */}
              <div className="pt-2 border-t border-neutral-100 space-y-3">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-neutral-800">
                    Handoff Items ({itemsToCreate.length})
                  </label>
                </div>

                {/* Staged Items list */}
                {itemsToCreate.length > 0 && (
                  <div className="space-y-1.5 max-h-36 overflow-y-auto">
                    {itemsToCreate.map((item, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-2 rounded bg-neutral-50 text-xs border border-neutral-200"
                      >
                        <div className="space-y-0.5">
                          <span className="font-medium text-neutral-900 block">{item.title}</span>
                          <span className="text-[10px] text-neutral-500 font-mono">
                            Status: {item.item_status} {item.record_id ? `• Record: ${item.record_id}` : ""}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => setItemsToCreate((prev) => prev.filter((_, i) => i !== idx))}
                          className="text-neutral-400 hover:text-rose-600 text-xs px-1"
                        >
                          ✕
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* Inline item adder */}
                <div className="rounded-lg bg-neutral-50 p-3 border border-neutral-200/80 space-y-2">
                  <span className="text-[10px] uppercase font-semibold text-neutral-500 block">
                    Add Handoff Item
                  </span>
                  <div className="grid grid-cols-3 gap-2">
                    <input
                      type="text"
                      value={newItemTitle}
                      onChange={(e) => setNewItemTitle(e.target.value)}
                      placeholder="Item Title (e.g. Rate limiter configuration)"
                      className="col-span-2 text-xs px-2.5 py-1.5 rounded border border-neutral-300 bg-white"
                    />
                    <select
                      value={newItemStatus}
                      onChange={(e) => setNewItemStatus(e.target.value as HandoffItemStatus)}
                      className="text-xs px-2 py-1.5 rounded border border-neutral-300 bg-white"
                    >
                      <option value="verified">Verified</option>
                      <option value="inferred">Inferred</option>
                      <option value="unresolved">Unresolved</option>
                      <option value="outdated">Outdated</option>
                    </select>
                  </div>
                  <input
                    type="text"
                    value={newItemDesc}
                    onChange={(e) => setNewItemDesc(e.target.value)}
                    placeholder="Description / Context (optional)"
                    className="w-full text-xs px-2.5 py-1.5 rounded border border-neutral-300 bg-white"
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <select
                      value={newItemAssignee}
                      onChange={(e) => setNewItemAssignee(e.target.value)}
                      className="text-xs px-2.5 py-1.5 rounded border border-neutral-300 bg-white"
                    >
                      <option value="">Unassigned</option>
                      {teamMembers.map((m) => (
                        <option key={m.user_id} value={m.user_id}>
                          {m.email || m.user_id.slice(0, 8)} ({m.role})
                        </option>
                      ))}
                    </select>
                    <input
                      type="date"
                      value={newItemDueDate}
                      onChange={(e) => setNewItemDueDate(e.target.value)}
                      className="text-xs px-2.5 py-1.5 rounded border border-neutral-300 bg-white"
                    />
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={newItemRecordId}
                      onChange={(e) => setNewItemRecordId(e.target.value)}
                      placeholder="Linked Record UUID (optional)"
                      className="flex-1 text-xs px-2.5 py-1.5 rounded border border-neutral-300 bg-white font-mono"
                    />
                    <button
                      type="button"
                      onClick={handleAddItemToForm}
                      className="px-3 py-1.5 bg-neutral-200 hover:bg-neutral-300 text-neutral-800 text-xs font-medium rounded transition-colors"
                    >
                      + Add Item
                    </button>
                  </div>
                </div>
              </div>

              <div className="pt-2 flex justify-end gap-2 border-t border-neutral-100">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-3 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingHandoff}
                  className="px-4 py-1.5 text-xs font-medium bg-neutral-900 text-white rounded-lg hover:bg-neutral-800 disabled:opacity-50"
                >
                  {isSubmittingHandoff ? "Creating Handoff..." : "Create Handoff"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Auto-Generate Dossier Modal */}
      {isGenerateModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl border border-neutral-200 w-full max-w-lg max-h-[90vh] overflow-y-auto animate-in fade-in zoom-in-95 duration-150">
            <div className="p-4 border-b border-neutral-100 flex items-center justify-between bg-gradient-to-r from-neutral-900 to-neutral-800 text-white">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-emerald-500/20 border border-emerald-400/30 flex items-center justify-center text-emerald-400">
                  <Sparkles className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    Auto-Generate Engineering Dossier
                  </h3>
                  <p className="text-[11px] text-neutral-300">
                    Extracts knowledge, commits, PRs, and Slack decisions into verified transfer items.
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => !isGenerating && setIsGenerateModalOpen(false)}
                disabled={isGenerating}
                className="text-neutral-400 hover:text-white text-xs p-1"
              >
                ✕
              </button>
            </div>

            {isGenerating ? (
              <div className="p-8 text-center space-y-4">
                <div className="relative w-12 h-12 mx-auto">
                  <div className="absolute inset-0 rounded-full border-2 border-emerald-500/20 animate-ping" />
                  <div className="w-12 h-12 rounded-full border-2 border-emerald-500 border-t-transparent animate-spin flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-emerald-500" />
                  </div>
                </div>
                <div className="space-y-1">
                  <h4 className="text-sm font-semibold text-neutral-900">
                    Synthesizing Dossier for {generateSubjectIdentifier}...
                  </h4>
                  <p className="text-xs text-neutral-500 max-w-sm mx-auto">
                    Analyzing Git commits, pull requests, Jira backlog, and Slack conversations with DSPy reasoning...
                  </p>
                </div>
                <div className="w-48 h-1.5 bg-neutral-100 rounded-full mx-auto overflow-hidden">
                  <div className="h-full bg-emerald-500 rounded-full animate-pulse w-3/4" />
                </div>
              </div>
            ) : (
              <form onSubmit={handleGenerateDossier} className="p-5 space-y-4">
                {generateError && (
                  <div className="rounded-lg bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-700 flex items-center gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    <span>{generateError}</span>
                  </div>
                )}

                {/* Suggestions / Auto-Detected Subjects */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-neutral-700">
                      Auto-Detected From Activity:
                    </label>
                    {isLoadingDetected && (
                      <span className="text-[10px] text-neutral-400 flex items-center gap-1">
                        <Loader2 className="w-3 h-3 animate-spin" /> Scanning sources...
                      </span>
                    )}
                  </div>

                  {detectedSubjects && (
                    <div className="space-y-2">
                      {detectedSubjects.engineers.length > 0 && (
                        <div>
                          <span className="text-[10px] font-medium text-neutral-400 block mb-1">
                            Engineers & Contributors:
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {detectedSubjects.engineers.map((eng) => (
                              <button
                                key={eng}
                                type="button"
                                onClick={() => {
                                  setGenerateSubjectIdentifier(eng);
                                  setGenerateSubjectType("person");
                                }}
                                className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors flex items-center gap-1 ${
                                  generateSubjectIdentifier === eng && generateSubjectType === "person"
                                    ? "bg-neutral-900 text-white border-neutral-900"
                                    : "bg-neutral-50 text-neutral-700 border-neutral-200 hover:bg-neutral-100"
                                }`}
                              >
                                <User className="w-3 h-3" />
                                <span>{eng}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {detectedSubjects.services.length > 0 && (
                        <div>
                          <span className="text-[10px] font-medium text-neutral-400 block mb-1">
                            Services & Repositories:
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {detectedSubjects.services.map((svc) => (
                              <button
                                key={svc}
                                type="button"
                                onClick={() => {
                                  setGenerateSubjectIdentifier(svc);
                                  setGenerateSubjectType("service");
                                }}
                                className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                                  generateSubjectIdentifier === svc && generateSubjectType === "service"
                                    ? "bg-neutral-900 text-white border-neutral-900"
                                    : "bg-neutral-50 text-neutral-700 border-neutral-200 hover:bg-neutral-100"
                                }`}
                              >
                                <span>{svc}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-3 gap-3 pt-1">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700 block">Subject Type</label>
                    <select
                      value={generateSubjectType}
                      onChange={(e) => setGenerateSubjectType(e.target.value as HandoffSubjectType)}
                      className="w-full text-xs px-2.5 py-2 rounded-lg border border-neutral-300 bg-white"
                    >
                      <option value="person">Person / Engineer</option>
                      <option value="service">Service / Component</option>
                    </select>
                  </div>

                  <div className="col-span-2 space-y-1">
                    <label className="text-xs font-medium text-neutral-700 block">
                      Target Identifier or Name
                    </label>
                    <input
                      type="text"
                      required
                      value={generateSubjectIdentifier}
                      onChange={(e) => setGenerateSubjectIdentifier(e.target.value)}
                      placeholder="e.g. Kabilesh M or auth-service"
                      className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-medium text-neutral-700 block">
                    Assignee / Recipient (Optional)
                  </label>
                  <select
                    value={generateRecipientUserId}
                    onChange={(e) => setGenerateRecipientUserId(e.target.value)}
                    className="w-full text-xs px-2.5 py-2 rounded-lg border border-neutral-300 bg-white"
                  >
                    <option value="">None (Unassigned)</option>
                    {teamMembers.map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.email || m.user_id.slice(0, 8)} ({m.role})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="pt-2 flex justify-end gap-2 border-t border-neutral-100">
                  <button
                    type="button"
                    onClick={() => setIsGenerateModalOpen(false)}
                    className="px-3 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!generateSubjectIdentifier.trim()}
                    className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium bg-neutral-900 text-white rounded-lg hover:bg-neutral-800 disabled:opacity-50 transition-colors"
                  >
                    <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Generate Dossier</span>
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Supabase Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onSuccess={refreshSession}
      />
    </div>
  );
}
