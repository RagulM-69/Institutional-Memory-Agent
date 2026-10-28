"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Users,
  UserPlus,
  Shield,
  ShieldCheck,
  UserCheck,
  Mail,
  Trash2,
  Edit2,
  Copy,
  Check,
  AlertCircle,
  CheckCircle2,
  Loader2,
  RefreshCw,
  Building,
  X,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { AuthModal } from "@/components/auth/AuthModal";
import {
  ActiveOrganization,
  AuthenticatedUser,
  TeamMember,
  MemberRole,
  InvitationSummary,
  InvitationCreatedResponse,
  OrganizationSummary,
} from "@/lib/types";
import {
  checkApiHealth,
  getCurrentOrg,
  getCurrentUser,
  listTeamMembers,
  updateMemberRole,
  removeMember,
  createInvitation,
  listInvitations,
  revokeInvitation,
  resendInvitation,
  listMyOrganizations,
  createOrganization,
  ApiError,
} from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

export default function TeamPage() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Active Tab
  const [activeTab, setActiveTab] = useState<"members" | "invitations" | "organizations">("members");

  // Data states
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [invitations, setInvitations] = useState<InvitationSummary[]>([]);
  const [myOrgs, setMyOrgs] = useState<OrganizationSummary[]>([]);
  const [isLoadingData, setIsLoadingData] = useState<boolean>(false);

  // Notification banners
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Invite Modal
  const [isInviteModalOpen, setIsInviteModalOpen] = useState<boolean>(false);
  const [inviteEmail, setInviteEmail] = useState<string>("");
  const [inviteRole, setInviteRole] = useState<MemberRole>("member");
  const [isSubmittingInvite, setIsSubmittingInvite] = useState<boolean>(false);
  const [createdInviteResult, setCreatedInviteResult] = useState<InvitationCreatedResponse | null>(null);
  const [copiedLink, setCopiedLink] = useState<boolean>(false);
  const [copiedCode, setCopiedCode] = useState<boolean>(false);

  // Create Org Modal
  const [isCreateOrgModalOpen, setIsCreateOrgModalOpen] = useState<boolean>(false);
  const [newOrgName, setNewOrgName] = useState<string>("");
  const [newOrgSlug, setNewOrgSlug] = useState<string>("");
  const [isCreatingOrg, setIsCreatingOrg] = useState<boolean>(false);

  // Role Edit Modal
  const [editingMember, setEditingMember] = useState<TeamMember | null>(null);
  const [editRoleVal, setEditRoleVal] = useState<MemberRole>("member");
  const [isUpdatingRole, setIsUpdatingRole] = useState<boolean>(false);

  // Delete Member Confirm
  const [deletingMember, setDeletingMember] = useState<TeamMember | null>(null);
  const [isDeletingMember, setIsDeletingMember] = useState<boolean>(false);

  const isAdmin = org?.role === "admin";
  const isTeamLeadOrAdmin = org?.role === "admin" || org?.role === "team_lead";
  const adminCount = members.filter((m) => m.role === "admin").length;

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

  const loadData = useCallback(async () => {
    if (!jwt) return;
    setIsLoadingData(true);
    setErrorMsg(null);

    try {
      if (org) {
        const mems = await listTeamMembers(jwt, org.org_id);
        setMembers(mems);

        if (isAdmin) {
          const invites = await listInvitations(jwt, org.org_id);
          setInvitations(invites);
        }
      }

      const orgs = await listMyOrganizations(jwt);
      setMyOrgs(orgs);
    } catch (e) {
      if (e instanceof ApiError) {
        setErrorMsg(e.message);
      } else {
        setErrorMsg("Failed to load team data.");
      }
    } finally {
      setIsLoadingData(false);
    }
  }, [jwt, org, isAdmin]);

  useEffect(() => {
    let cancelled = false;
    async function initData() {
      if (!cancelled && jwt) {
        await loadData();
      }
    }
    initData();
    return () => {
      cancelled = true;
    };
  }, [jwt, org, loadData]);

  // Handle Invite Creation
  const handleCreateInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt || !org) return;

    setIsSubmittingInvite(true);
    setErrorMsg(null);

    try {
      const res = await createInvitation(
        { email: inviteEmail.trim(), role: inviteRole },
        jwt,
        org.org_id
      );
      setCreatedInviteResult(res);
      setSuccessMsg(`Invitation created for ${res.email}`);
      await loadData();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to generate invitation.");
      }
    } finally {
      setIsSubmittingInvite(false);
    }
  };

  // Handle Resend Invite
  const handleResendInvite = async (invitationId: string) => {
    if (!jwt || !org) return;
    setErrorMsg(null);
    try {
      const res = await resendInvitation(invitationId, jwt, org.org_id);
      setCreatedInviteResult(res);
      setIsInviteModalOpen(true);
      setSuccessMsg(`Invitation refreshed for ${res.email}`);
      await loadData();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to resend invitation.");
      }
    }
  };

  // Handle Revoke Invite
  const handleRevokeInvite = async (invitationId: string) => {
    if (!jwt || !org) return;
    setErrorMsg(null);
    try {
      await revokeInvitation(invitationId, jwt, org.org_id);
      setSuccessMsg("Invitation revoked.");
      await loadData();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to revoke invitation.");
      }
    }
  };

  // Handle Update Role
  const handleUpdateRole = async () => {
    if (!jwt || !org || !editingMember) return;
    setIsUpdatingRole(true);
    setErrorMsg(null);

    try {
      await updateMemberRole(
        editingMember.user_id,
        { role: editRoleVal },
        jwt,
        org.org_id
      );
      setSuccessMsg(`Role updated for member.`);
      setEditingMember(null);
      await loadData();
      await refreshSession();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to update role.");
      }
    } finally {
      setIsUpdatingRole(false);
    }
  };

  // Handle Remove Member
  const handleRemoveMember = async () => {
    if (!jwt || !org || !deletingMember) return;
    setIsDeletingMember(true);
    setErrorMsg(null);

    try {
      await removeMember(deletingMember.user_id, jwt, org.org_id);
      setSuccessMsg(`Member removed from organization.`);
      setDeletingMember(null);
      await loadData();
      await refreshSession();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to remove member.");
      }
    } finally {
      setIsDeletingMember(false);
    }
  };

  // Handle Create Organization
  const handleCreateOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt) return;
    setIsCreatingOrg(true);
    setErrorMsg(null);

    try {
      const created = await createOrganization(
        { name: newOrgName.trim(), slug: newOrgSlug.trim() },
        jwt
      );
      setSuccessMsg(`Organization "${created.name}" created successfully.`);
      setIsCreateOrgModalOpen(false);
      setNewOrgName("");
      setNewOrgSlug("");
      await refreshSession();
      await loadData();
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Failed to create organization.");
      }
    } finally {
      setIsCreatingOrg(false);
    }
  };

  const handleCopyLink = () => {
    if (!createdInviteResult) return;
    navigator.clipboard.writeText(createdInviteResult.invitation_link);
    setCopiedLink(true);
    setTimeout(() => setCopiedLink(false), 2000);
  };

  const handleCopyCode = () => {
    if (!createdInviteResult) return;
    const code = createdInviteResult.raw_code || createdInviteResult.code;
    if (code) {
      navigator.clipboard.writeText(code);
      setCopiedCode(true);
      setTimeout(() => setCopiedCode(false), 2000);
    }
  };

  const handleSignOut = async () => {
    const sb = getSupabase();
    if (sb) {
      await sb.auth.signOut();
    }
    setJwt(null);
    setUser(null);
    setOrg(null);
  };

  const roleBadge = (role: MemberRole | string) => {
    if (role === "admin") {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300">
          <ShieldCheck className="w-3 h-3 text-amber-700" />
          Admin
        </span>
      );
    }
    if (role === "team_lead") {
      return (
        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-100 text-indigo-800 border border-indigo-300">
          <Shield className="w-3 h-3 text-indigo-700" />
          Team Lead
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-neutral-100 text-neutral-700 border border-neutral-200">
        <UserCheck className="w-3 h-3 text-neutral-500" />
        Member
      </span>
    );
  };

  return (
    <div className="flex h-screen bg-[#fafafa] text-neutral-900 overflow-hidden font-sans">
      <AppSidebar
        currentPath="/team"
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        apiOnline={apiOnline}
        org={org}
        user={user}
        onSignOut={handleSignOut}
        onSignIn={() => setIsAuthModalOpen(true)}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <AppHeader
          user={user}
          org={org}
          apiOnline={apiOnline}
          onOpenAuth={() => setIsAuthModalOpen(true)}
          onSignOut={handleSignOut}
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        />

        <main className="flex-1 overflow-y-auto p-4 md:p-8">
          <div className="max-w-6xl mx-auto space-y-6">
            {/* Header info */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-neutral-200 pb-5">
              <div>
                <div className="flex items-center gap-3">
                  <h1 className="text-2xl font-bold tracking-tight text-neutral-900">
                    Team & Organization
                  </h1>
                  {org && roleBadge(org.role)}
                </div>
                <p className="text-sm text-neutral-500 mt-1">
                  {org
                    ? `Managing members, roles, and access invitations for ${org.name}`
                    : "Manage your organizations and team memberships"}
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={loadData}
                  disabled={isLoadingData || !jwt}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-neutral-600 bg-white border border-neutral-200 rounded-lg hover:bg-neutral-50 disabled:opacity-50 transition-colors shadow-2xs"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${isLoadingData ? "animate-spin" : ""}`} />
                  Refresh
                </button>

                <button
                  onClick={() => setIsCreateOrgModalOpen(true)}
                  disabled={!jwt}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-neutral-700 bg-white border border-neutral-300 rounded-lg hover:bg-neutral-50 shadow-2xs"
                >
                  <Building className="w-3.5 h-3.5" />
                  New Org
                </button>

                {isAdmin && (
                  <button
                    onClick={() => {
                      setCreatedInviteResult(null);
                      setInviteEmail("");
                      setInviteRole("member");
                      setIsInviteModalOpen(true);
                    }}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold text-white bg-neutral-900 rounded-lg hover:bg-neutral-800 shadow-2xs transition-colors"
                  >
                    <UserPlus className="w-3.5 h-3.5" />
                    Invite Member
                  </button>
                )}
              </div>
            </div>

            {/* Notifications */}
            {errorMsg && (
              <div className="flex items-start gap-3 p-3.5 rounded-lg bg-red-50 border border-red-200 text-red-800 text-sm">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-600" />
                <div className="flex-1">{errorMsg}</div>
                <button onClick={() => setErrorMsg(null)} className="text-red-500 hover:text-red-700">
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}

            {successMsg && (
              <div className="flex items-start gap-3 p-3.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm">
                <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-600" />
                <div className="flex-1">{successMsg}</div>
                <button onClick={() => setSuccessMsg(null)} className="text-emerald-500 hover:text-emerald-700">
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}

            {/* Tabs */}
            <div className="flex border-b border-neutral-200 gap-4 sm:gap-6 text-sm font-medium overflow-x-auto whitespace-nowrap scrollbar-none pb-0.5">
              <button
                onClick={() => setActiveTab("members")}
                className={`shrink-0 pb-3 flex items-center gap-2 border-b-2 transition-colors ${
                  activeTab === "members"
                    ? "border-neutral-900 text-neutral-900 font-semibold"
                    : "border-transparent text-neutral-500 hover:text-neutral-700"
                }`}
              >
                <Users className="w-4 h-4" />
                Members ({members.length})
              </button>

              {isAdmin && (
                <button
                  onClick={() => setActiveTab("invitations")}
                  className={`shrink-0 pb-3 flex items-center gap-2 border-b-2 transition-colors ${
                    activeTab === "invitations"
                      ? "border-neutral-900 text-neutral-900 font-semibold"
                      : "border-transparent text-neutral-500 hover:text-neutral-700"
                  }`}
                >
                  <Mail className="w-4 h-4" />
                  Invitations ({invitations.filter((i) => i.status === "pending").length} Pending)
                </button>
              )}

              <button
                onClick={() => setActiveTab("organizations")}
                className={`shrink-0 pb-3 flex items-center gap-2 border-b-2 transition-colors ${
                  activeTab === "organizations"
                    ? "border-neutral-900 text-neutral-900 font-semibold"
                    : "border-transparent text-neutral-500 hover:text-neutral-700"
                }`}
              >
                <Building className="w-4 h-4" />
                My Organizations ({myOrgs.length})
              </button>
            </div>

            {/* TAB: Members */}
            {activeTab === "members" && (
              <div className="bg-white border border-neutral-200/80 rounded-xl shadow-2xs overflow-hidden">
                <div className="px-5 py-3.5 border-b border-neutral-100 bg-neutral-50/50 flex items-center justify-between">
                  <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
                    Organization Directory
                  </span>
                  {!isTeamLeadOrAdmin && (
                    <span className="text-xs text-neutral-400">
                      Standard members view their personal profile only
                    </span>
                  )}
                </div>

                <div className="divide-y divide-neutral-100">
                  {members.length === 0 ? (
                    <div className="p-8 text-center text-sm text-neutral-500">
                      {isLoadingData ? (
                        <div className="flex items-center justify-center gap-2">
                          <Loader2 className="w-4 h-4 animate-spin text-neutral-400" />
                          Loading members...
                        </div>
                      ) : (
                        "No members found."
                      )}
                    </div>
                  ) : (
                    members.map((m) => {
                      const isTargetSoleAdmin = m.role === "admin" && adminCount <= 1;
                      return (
                        <div
                          key={m.id}
                          className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-neutral-50/60 transition-colors"
                        >
                          <div className="flex items-center gap-3.5">
                            <div className="w-9 h-9 rounded-full bg-neutral-100 border border-neutral-200 flex items-center justify-center font-medium text-neutral-600 text-xs">
                              {m.email ? m.email[0].toUpperCase() : "U"}
                            </div>
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold text-sm text-neutral-900">
                                  {m.email || `User ${m.user_id.slice(0, 8)}...`}
                                </span>
                                {m.is_self && (
                                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-600 border border-neutral-200">
                                    You
                                  </span>
                                )}
                              </div>
                              <span className="text-xs text-neutral-400 font-mono">
                                Member since {new Date(m.created_at).toLocaleDateString()}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-3">
                            {roleBadge(m.role)}

                            {isAdmin && (
                              <div className="flex items-center gap-1 ml-2">
                                <button
                                  onClick={() => {
                                    setEditingMember(m);
                                    setEditRoleVal(m.role);
                                  }}
                                  disabled={isTargetSoleAdmin}
                                  title={
                                    isTargetSoleAdmin
                                      ? "Sole administrator cannot be demoted."
                                      : "Change role"
                                  }
                                  className="p-1.5 text-neutral-500 hover:text-neutral-900 hover:bg-neutral-100 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                  <Edit2 className="w-3.5 h-3.5" />
                                </button>

                                <button
                                  onClick={() => setDeletingMember(m)}
                                  disabled={isTargetSoleAdmin}
                                  title={
                                    isTargetSoleAdmin
                                      ? "Sole administrator cannot be removed."
                                      : "Remove from organization"
                                  }
                                  className="p-1.5 text-neutral-500 hover:text-red-600 hover:bg-red-50 rounded-md disabled:opacity-40 disabled:cursor-not-allowed"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}

            {/* TAB: Invitations (Admin only) */}
            {activeTab === "invitations" && isAdmin && (
              <div className="bg-white border border-neutral-200/80 rounded-xl shadow-2xs overflow-hidden">
                <div className="px-5 py-3.5 border-b border-neutral-100 bg-neutral-50/50 flex items-center justify-between">
                  <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
                    Invitations History & Pending Requests
                  </span>
                  <span className="text-xs text-neutral-400">
                    Tokens and codes are securely hashed at rest
                  </span>
                </div>

                <div className="divide-y divide-neutral-100">
                  {invitations.length === 0 ? (
                    <div className="p-8 text-center text-sm text-neutral-500">
                      No invitations issued yet.
                    </div>
                  ) : (
                    invitations.map((inv) => {
                      const isExpired = new Date(inv.expires_at) < new Date();
                      return (
                        <div
                          key={inv.id}
                          className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-neutral-50/60 transition-colors"
                        >
                          <div className="flex items-center gap-3.5">
                            <div className="w-9 h-9 rounded-full bg-neutral-100 border border-neutral-200 flex items-center justify-center font-medium text-neutral-600 text-xs">
                              <Mail className="w-4 h-4 text-neutral-400" />
                            </div>
                            <div>
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-semibold text-sm text-neutral-900">
                                  {inv.email}
                                </span>
                                {roleBadge(inv.role)}
                              </div>
                              <div className="text-xs text-neutral-400 flex items-center gap-2 mt-0.5">
                                <span>Invited {new Date(inv.created_at).toLocaleDateString()}</span>
                                <span>•</span>
                                <span>Expires {new Date(inv.expires_at).toLocaleDateString()}</span>
                              </div>
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center gap-2">
                            {inv.status === "pending" && !isExpired && (
                              <span className="px-2 py-0.5 text-xs font-semibold rounded bg-amber-50 text-amber-700 border border-amber-200">
                                Pending
                              </span>
                            )}
                            {inv.status === "accepted" && (
                              <span className="px-2 py-0.5 text-xs font-semibold rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                                Accepted
                              </span>
                            )}
                            {(inv.status === "expired" || (inv.status === "pending" && isExpired)) && (
                              <span className="px-2 py-0.5 text-xs font-semibold rounded bg-neutral-100 text-neutral-600 border border-neutral-200">
                                Expired
                              </span>
                            )}
                            {inv.status === "revoked" && (
                              <span className="px-2 py-0.5 text-xs font-semibold rounded bg-red-50 text-red-600 border border-red-200">
                                Revoked
                              </span>
                            )}

                            {inv.status === "pending" && !isExpired && (
                              <div className="flex items-center gap-1 ml-2">
                                <button
                                  onClick={() => handleResendInvite(inv.id)}
                                  className="text-xs px-2 py-1 text-neutral-600 hover:text-neutral-900 hover:bg-neutral-100 rounded border border-neutral-200"
                                >
                                  Resend
                                </button>
                                <button
                                  onClick={() => handleRevokeInvite(inv.id)}
                                  className="text-xs px-2 py-1 text-red-600 hover:text-red-800 hover:bg-red-50 rounded border border-red-200"
                                >
                                  Revoke
                                </button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            )}

            {/* TAB: Organizations */}
            {activeTab === "organizations" && (
              <div className="bg-white border border-neutral-200/80 rounded-xl shadow-2xs overflow-hidden">
                <div className="px-5 py-3.5 border-b border-neutral-100 bg-neutral-50/50 flex items-center justify-between">
                  <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider">
                    Your Organization Memberships
                  </span>
                  <button
                    onClick={() => setIsCreateOrgModalOpen(true)}
                    className="text-xs font-semibold text-neutral-900 hover:underline flex items-center gap-1"
                  >
                    <Building className="w-3.5 h-3.5" />
                    Create Organization
                  </button>
                </div>

                <div className="divide-y divide-neutral-100">
                  {myOrgs.map((o) => {
                    const isCurrent = org?.org_id === o.org_id;
                    return (
                      <div
                        key={o.org_id}
                        className={`p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-neutral-50/60 transition-colors ${
                          isCurrent ? "bg-amber-50/20" : ""
                        }`}
                      >
                        <div>
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-sm text-neutral-900">
                              {o.name}
                            </span>
                            <span className="text-xs text-neutral-400 font-mono">
                              /{o.slug}
                            </span>
                            {isCurrent && (
                              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-neutral-900 text-white">
                                Active
                              </span>
                            )}
                          </div>
                          <span className="text-xs text-neutral-400">
                            Joined {new Date(o.created_at).toLocaleDateString()}
                          </span>
                        </div>

                        <div className="flex items-center gap-3">
                          {roleBadge(o.role)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </main>
      </div>

      {/* MODAL: Invite Member */}
      {isInviteModalOpen && (
        <div className="fixed inset-0 z-50 bg-neutral-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-md w-full border border-neutral-200 shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-5 border-b border-neutral-100 flex items-center justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <UserPlus className="w-4 h-4 text-neutral-900" />
                <h3 className="font-bold text-sm text-neutral-900">
                  {createdInviteResult ? "Invitation Generated" : "Invite New Member"}
                </h3>
              </div>
              <button
                onClick={() => {
                  setIsInviteModalOpen(false);
                  setCreatedInviteResult(null);
                }}
                className="text-neutral-400 hover:text-neutral-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {createdInviteResult ? (
              <div className="p-5 space-y-4">
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800 flex items-start gap-2">
                  <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600 mt-0.5" />
                  <span>
                    Invitation ready for <strong>{createdInviteResult.email}</strong> as{" "}
                    <strong>{createdInviteResult.role}</strong>. Share the link or code below.
                  </span>
                </div>

                <div>
                  <label className="text-xs font-medium text-neutral-600 block mb-1">
                    Invitation Link (Single-use)
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      readOnly
                      value={createdInviteResult.invitation_link}
                      className="text-xs font-mono bg-neutral-50 border border-neutral-200 rounded-md px-2.5 py-1.5 flex-1 select-all"
                    />
                    <button
                      onClick={handleCopyLink}
                      className="px-2.5 py-1.5 text-xs font-medium bg-neutral-100 hover:bg-neutral-200 text-neutral-700 rounded-md flex items-center gap-1"
                    >
                      {copiedLink ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      {copiedLink ? "Copied" : "Copy"}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium text-neutral-600 block mb-1">
                    Backup Code (for manual lookup)
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      type="text"
                      readOnly
                      value={createdInviteResult.raw_code || createdInviteResult.code || ""}
                      className="text-xs font-mono font-semibold bg-neutral-50 border border-neutral-200 rounded-md px-2.5 py-1.5 flex-1 select-all"
                    />
                    <button
                      onClick={handleCopyCode}
                      className="px-2.5 py-1.5 text-xs font-medium bg-neutral-100 hover:bg-neutral-200 text-neutral-700 rounded-md flex items-center gap-1"
                    >
                      {copiedCode ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                      {copiedCode ? "Copied" : "Copy"}
                    </button>
                  </div>
                </div>

                <div className="p-2.5 bg-neutral-50 border border-neutral-200 rounded text-[11px] text-neutral-500">
                  Notice: Raw credentials are shown strictly once. Only secure SHA-256 hashes are stored at rest.
                </div>

                <div className="pt-2 flex justify-end">
                  <button
                    onClick={() => {
                      setIsInviteModalOpen(false);
                      setCreatedInviteResult(null);
                    }}
                    className="px-4 py-1.5 text-xs font-semibold bg-neutral-900 text-white rounded-lg hover:bg-neutral-800"
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleCreateInvite} className="p-5 space-y-4">
                <div>
                  <label className="text-xs font-medium text-neutral-700 block mb-1">
                    Recipient Email Address
                  </label>
                  <input
                    type="email"
                    required
                    placeholder="colleague@example.com"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    className="w-full text-xs border border-neutral-300 rounded-lg px-3 py-2 text-neutral-900 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                  />
                  <span className="text-[11px] text-neutral-400 mt-1 block">
                    The invitation can only be accepted by an account matching this email.
                  </span>
                </div>

                <div>
                  <label className="text-xs font-medium text-neutral-700 block mb-1">
                    Assigned Role
                  </label>
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as MemberRole)}
                    className="w-full text-xs border border-neutral-300 rounded-lg px-3 py-2 text-neutral-900 focus:outline-hidden focus:ring-1 focus:ring-neutral-900 bg-white"
                  >
                    <option value="member">Member — Read knowledge & execute assigned handoff items</option>
                    <option value="team_lead">Team Lead — Manage notes, gaps, handoffs, and assignees</option>
                    <option value="admin">Admin — Full organization access, member invitations & connector setup</option>
                  </select>
                </div>

                <div className="pt-2 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setIsInviteModalOpen(false)}
                    className="px-3.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-100 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={isSubmittingInvite || !inviteEmail.trim()}
                    className="px-4 py-1.5 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {isSubmittingInvite && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    Create Invitation
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* MODAL: Create Organization */}
      {isCreateOrgModalOpen && (
        <div className="fixed inset-0 z-50 bg-neutral-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-md w-full border border-neutral-200 shadow-xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-5 border-b border-neutral-100 flex items-center justify-between">
              <div className="flex flex-wrap items-center gap-2">
                <Building className="w-4 h-4 text-neutral-900" />
                <h3 className="font-bold text-sm text-neutral-900">Create New Organization</h3>
              </div>
              <button
                onClick={() => setIsCreateOrgModalOpen(false)}
                className="text-neutral-400 hover:text-neutral-600"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleCreateOrg} className="p-5 space-y-4">
              <div>
                <label className="text-xs font-medium text-neutral-700 block mb-1">
                  Organization Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="Acme Engineering"
                  value={newOrgName}
                  onChange={(e) => {
                    setNewOrgName(e.target.value);
                    if (!newOrgSlug || newOrgSlug === newOrgName.toLowerCase().replace(/[^a-z0-9]+/g, "-")) {
                      setNewOrgSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 32));
                    }
                  }}
                  className="w-full text-xs border border-neutral-300 rounded-lg px-3 py-2 text-neutral-900 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                />
              </div>

              <div>
                <label className="text-xs font-medium text-neutral-700 block mb-1">
                  Identifier Slug
                </label>
                <input
                  type="text"
                  required
                  pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
                  placeholder="acme-engineering"
                  value={newOrgSlug}
                  onChange={(e) => setNewOrgSlug(e.target.value.toLowerCase())}
                  className="w-full text-xs font-mono border border-neutral-300 rounded-lg px-3 py-2 text-neutral-900 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                />
                <span className="text-[11px] text-neutral-400 mt-1 block">
                  Lowercase alphanumeric with single hyphens (e.g. acme-corp)
                </span>
              </div>

              <div className="p-2.5 bg-neutral-50 border border-neutral-200 rounded text-[11px] text-neutral-500">
                You will automatically become the initial administrator of this organization.
              </div>

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsCreateOrgModalOpen(false)}
                  className="px-3.5 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isCreatingOrg || !newOrgName.trim() || !newOrgSlug.trim()}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg disabled:opacity-50 flex items-center gap-1.5"
                >
                  {isCreatingOrg && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Create Organization
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Change Member Role */}
      {editingMember && (
        <div className="fixed inset-0 z-50 bg-neutral-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-sm w-full border border-neutral-200 shadow-xl overflow-hidden">
            <div className="p-5 border-b border-neutral-100 flex items-center justify-between">
              <h3 className="font-bold text-sm text-neutral-900">Modify Member Role</h3>
              <button onClick={() => setEditingMember(null)} className="text-neutral-400 hover:text-neutral-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <p className="text-xs text-neutral-600">
                Update role permissions for <strong>{editingMember.email || editingMember.user_id}</strong>:
              </p>

              <select
                value={editRoleVal}
                onChange={(e) => setEditRoleVal(e.target.value as MemberRole)}
                className="w-full text-xs border border-neutral-300 rounded-lg px-3 py-2 text-neutral-900 bg-white"
              >
                <option value="member">Member</option>
                <option value="team_lead">Team Lead</option>
                <option value="admin">Admin</option>
              </select>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingMember(null)}
                  className="px-3.5 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  onClick={handleUpdateRole}
                  disabled={isUpdatingRole}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-neutral-900 hover:bg-neutral-800 rounded-lg flex items-center gap-1.5"
                >
                  {isUpdatingRole && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Save Role
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: Confirm Delete Member */}
      {deletingMember && (
        <div className="fixed inset-0 z-50 bg-neutral-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-xl max-w-sm w-full border border-neutral-200 shadow-xl overflow-hidden">
            <div className="p-5 border-b border-neutral-100 flex items-center justify-between">
              <h3 className="font-bold text-sm text-neutral-900">Remove Member</h3>
              <button onClick={() => setDeletingMember(null)} className="text-neutral-400 hover:text-neutral-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <p className="text-xs text-neutral-600">
                Are you sure you want to remove <strong>{deletingMember.email || deletingMember.user_id}</strong> from{" "}
                <strong>{org?.name}</strong>? They will lose all access immediately.
              </p>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setDeletingMember(null)}
                  className="px-3.5 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRemoveMember}
                  disabled={isDeletingMember}
                  className="px-4 py-1.5 text-xs font-semibold text-white bg-red-600 hover:bg-red-700 rounded-lg flex items-center gap-1.5"
                >
                  {isDeletingMember && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  Remove Member
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onSuccess={refreshSession}
      />
    </div>
  );
}
