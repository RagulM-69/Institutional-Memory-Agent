"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  BookOpen,
  FileText,
  Plus,
  Calendar,
  ExternalLink,
  Layers,
  AlertCircle,
  ArrowRight,
  Shield,
  ShieldAlert,
  RefreshCw,
  Clock,
  Trash2,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { AuthModal } from "@/components/auth/AuthModal";
import {
  ActiveOrganization,
  AuthenticatedUser,
  KnowledgeNote,
  MeetingSummary,
} from "@/lib/types";
import {
  checkApiHealth,
  getCurrentOrg,
  getCurrentUser,
  listKnowledgeNotes,
  createKnowledgeNote,
  deleteKnowledgeNote,
  listMeetings,
  ingestMeeting,
  deleteMeeting,
  ApiError,
} from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

export default function KnowledgeHub() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Tab State
  const [activeTab, setActiveTab] = useState<"notes" | "meetings">("notes");

  // Notes State
  const [notes, setNotes] = useState<KnowledgeNote[]>([]);
  const [isLoadingNotes, setIsLoadingNotes] = useState<boolean>(false);
  const [isCreateNoteModalOpen, setIsCreateNoteModalOpen] = useState<boolean>(false);
  const [noteTitle, setNoteTitle] = useState<string>("");
  const [noteContent, setNoteContent] = useState<string>("");
  const [noteRecordIds, setNoteRecordIds] = useState<string>("");
  const [isSubmittingNote, setIsSubmittingNote] = useState<boolean>(false);
  const [noteError, setNoteError] = useState<string | null>(null);

  // Meetings State
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [isLoadingMeetings, setIsLoadingMeetings] = useState<boolean>(false);
  const [isIngestMeetingModalOpen, setIsIngestMeetingModalOpen] = useState<boolean>(false);
  const [meetingTitle, setMeetingTitle] = useState<string>("");
  const [meetingContent, setMeetingContent] = useState<string>("");
  const [meetingDate, setMeetingDate] = useState<string>("");
  const [isSubmittingMeeting, setIsSubmittingMeeting] = useState<boolean>(false);
  const [meetingError, setMeetingError] = useState<string | null>(null);

  const [generalError, setGeneralError] = useState<string | null>(null);

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

  // Load content whenever tab, jwt, or org changes
  const fetchActiveTabContent = useCallback(async () => {
    if (!jwt || !org) return;
    setGeneralError(null);

    if (activeTab === "notes") {
      setIsLoadingNotes(true);
      try {
        const data = await listKnowledgeNotes(jwt, org?.org_id);
        setNotes(data);
      } catch (err: unknown) {
        setGeneralError(err instanceof Error ? err.message : "Failed to load notes");
      } finally {
        setIsLoadingNotes(false);
      }
    } else {
      setIsLoadingMeetings(true);
      try {
        const data = await listMeetings(jwt, org?.org_id);
        setMeetings(data);
      } catch (err: unknown) {
        setGeneralError(err instanceof Error ? err.message : "Failed to load meetings");
      } finally {
        setIsLoadingMeetings(false);
      }
    }
  }, [jwt, activeTab, org]);

  useEffect(() => {
    let cancelled = false;
    async function executeLoad() {
      if (!cancelled && jwt) {
        await fetchActiveTabContent();
      }
    }
    executeLoad();
    return () => {
      cancelled = true;
    };
  }, [jwt, fetchActiveTabContent]);

  // Handle Note Submission
  const handleCreateNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt) return;
    setIsSubmittingNote(true);
    setNoteError(null);

    const recordIdsParsed = noteRecordIds
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

    try {
      await createKnowledgeNote(
        {
          title: noteTitle.trim(),
          content: noteContent.trim(),
          record_ids: recordIdsParsed.length > 0 ? recordIdsParsed : undefined,
        },
        jwt,
        org?.org_id
      );

      setNoteTitle("");
      setNoteContent("");
      setNoteRecordIds("");
      setIsCreateNoteModalOpen(false);
      await fetchActiveTabContent();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create note";
      setNoteError(msg);
    } finally {
      setIsSubmittingNote(false);
    }
  };

  // Handle Meeting Ingestion
  const handleIngestMeeting = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!jwt) return;
    setIsSubmittingMeeting(true);
    setMeetingError(null);

    try {
      await ingestMeeting(
        {
          title: meetingTitle.trim(),
          content: meetingContent.trim(),
          meeting_date: meetingDate ? new Date(meetingDate).toISOString() : undefined,
        },
        jwt,
        org?.org_id
      );

      setMeetingTitle("");
      setMeetingContent("");
      setMeetingDate("");
      setIsIngestMeetingModalOpen(false);
      await fetchActiveTabContent();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to ingest transcript";
      setMeetingError(msg);
    } finally {
      setIsSubmittingMeeting(false);
    }
  };

  const handleDeleteNote = async (noteId: string) => {
    if (!jwt || !org) return;
    const confirmed = window.confirm("Are you sure you want to delete this knowledge note?");
    if (!confirmed) return;

    try {
      await deleteKnowledgeNote(noteId, jwt, org.org_id);
      await fetchActiveTabContent();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete knowledge note";
      setGeneralError(msg);
    }
  };

  const handleDeleteMeeting = async (meetingId: string) => {
    if (!jwt || !org) return;
    const confirmed = window.confirm(
      "Are you sure you want to delete this meeting transcript and its indexed vector embeddings?"
    );
    if (!confirmed) return;

    try {
      await deleteMeeting(meetingId, jwt, org.org_id);
      await fetchActiveTabContent();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete meeting transcript";
      setGeneralError(msg);
    }
  };

  return (
    <div className="flex h-screen bg-[#fcfcfc] text-neutral-900 font-sans antialiased overflow-hidden">
      {/* Navigation Sidebar */}
      <AppSidebar
        currentPath="/knowledge"
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

        <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
          {/* Header Title & Tab Controls */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-neutral-200/80 pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-neutral-900 flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-neutral-700" />
                <span>Knowledge Hub</span>
              </h1>
              <p className="text-xs text-neutral-500 mt-1">
                Capture human rationale notes and ingest meeting transcripts with deterministic local embeddings.
              </p>
            </div>

            {/* Action Button */}
            {jwt && org && (
              <div className="flex items-center gap-2">
                {activeTab === "notes" ? (
                  <button
                    type="button"
                    onClick={() => setIsCreateNoteModalOpen(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800 transition-colors shadow-xs"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>New Knowledge Note</span>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setIsIngestMeetingModalOpen(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800 transition-colors shadow-xs"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Ingest Transcript</span>
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Tab Navigation */}
          <div className="flex border-b border-neutral-200 text-xs font-medium space-x-6">
            <button
              type="button"
              onClick={() => setActiveTab("notes")}
              className={`pb-2.5 transition-colors border-b-2 flex items-center gap-2 ${
                activeTab === "notes"
                  ? "border-neutral-900 text-neutral-900 font-semibold"
                  : "border-transparent text-neutral-500 hover:text-neutral-800"
              }`}
            >
              <FileText className="w-4 h-4" />
              <span>Personal Knowledge Notes</span>
              {notes.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-neutral-100 text-neutral-600 font-mono">
                  {notes.length}
                </span>
              )}
            </button>

            <button
              type="button"
              onClick={() => setActiveTab("meetings")}
              className={`pb-2.5 transition-colors border-b-2 flex items-center gap-2 ${
                activeTab === "meetings"
                  ? "border-neutral-900 text-neutral-900 font-semibold"
                  : "border-transparent text-neutral-500 hover:text-neutral-800"
              }`}
            >
              <Calendar className="w-4 h-4" />
              <span>Meeting Transcripts</span>
              {meetings.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-neutral-100 text-neutral-600 font-mono">
                  {meetings.length}
                </span>
              )}
            </button>
          </div>

          {/* General Error Banner */}
          {generalError && (
            <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
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
                  Sign in with your organization account to view and capture institutional knowledge.
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

          {/* Tab 1: Knowledge Notes Content */}
          {jwt && org && activeTab === "notes" && (
            <div className="space-y-4">
              {isLoadingNotes ? (
                <div className="py-12 text-center text-xs text-neutral-400">
                  Loading knowledge notes...
                </div>
              ) : notes.length === 0 ? (
                <div className="rounded-xl border border-dashed border-neutral-300 p-8 text-center space-y-2 bg-white">
                  <FileText className="w-7 h-7 text-neutral-400 mx-auto" />
                  <h3 className="text-sm font-semibold text-neutral-800">No knowledge notes yet</h3>
                  <p className="text-xs text-neutral-500 max-w-md mx-auto">
                    Capture personal rationale notes and bridge context between architectural decisions and codebases.
                  </p>
                </div>
              ) : (
                <div className="grid gap-3">
                  {notes.map((note) => (
                    <div
                      key={note.id}
                      className="rounded-xl border border-neutral-200 bg-white p-4 shadow-xs space-y-2.5 transition-shadow hover:shadow-sm"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                              Human Contributed
                            </span>
                            <span className="text-[11px] text-neutral-400 font-mono">
                              Status: {note.status}
                            </span>
                          </div>
                          <h2 className="text-sm font-semibold text-neutral-900">
                            {note.title}
                          </h2>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-[11px] text-neutral-400 flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {new Date(note.created_at).toLocaleDateString()}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleDeleteNote(note.id)}
                            className="p-1 text-neutral-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors"
                            title="Delete knowledge note"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      <div className="text-xs text-neutral-700 leading-relaxed whitespace-pre-wrap">
                        {note.content}
                      </div>

                      {/* Linked Source Records */}
                      {note.linked_records && note.linked_records.length > 0 && (
                        <div className="pt-2 border-t border-neutral-100 space-y-1.5">
                          <span className="text-[10px] uppercase font-semibold text-neutral-400 block tracking-wider">
                            Linked Evidence Records ({note.linked_records.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {note.linked_records.map((rec) => (
                              <span
                                key={rec.id}
                                className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-neutral-100 text-neutral-700 border border-neutral-200/80 font-mono"
                              >
                                <ExternalLink className="w-3 h-3 text-neutral-400" />
                                <span>{rec.title || rec.external_id}</span>
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Tab 2: Meeting Transcripts Content */}
          {jwt && org && activeTab === "meetings" && (
            <div className="space-y-4">
              {isLoadingMeetings ? (
                <div className="py-12 text-center text-xs text-neutral-400">
                  Loading meeting transcripts...
                </div>
              ) : meetings.length === 0 ? (
                <div className="rounded-xl border border-dashed border-neutral-300 p-8 text-center space-y-2 bg-white">
                  <Calendar className="w-7 h-7 text-neutral-400 mx-auto" />
                  <h3 className="text-sm font-semibold text-neutral-800">No meeting transcripts indexed</h3>
                  <p className="text-xs text-neutral-500 max-w-md mx-auto">
                    Paste raw meeting notes or synthesis transcripts. Chunks and 384d vector embeddings are generated atomically.
                  </p>
                </div>
              ) : (
                <div className="grid gap-3">
                  {meetings.map((m) => (
                    <div
                      key={m.id}
                      className="rounded-xl border border-neutral-200 bg-white p-4 shadow-xs space-y-2 transition-shadow hover:shadow-sm"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-50 text-blue-800 border border-blue-200">
                              Meeting Transcript
                            </span>
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-neutral-100 text-neutral-600">
                              {m.chunk_count} Chunks Indexed
                            </span>
                          </div>
                          <h2 className="text-sm font-semibold text-neutral-900">
                            {m.title}
                          </h2>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-[11px] text-neutral-400 flex items-center gap-1">
                            <Calendar className="w-3 h-3" />
                            {m.meeting_date ? new Date(m.meeting_date).toLocaleDateString() : new Date(m.created_at).toLocaleDateString()}
                          </span>
                          <button
                            type="button"
                            onClick={() => handleDeleteMeeting(m.id)}
                            className="p-1 text-neutral-400 hover:text-rose-600 hover:bg-rose-50 rounded-md transition-colors"
                            title="Delete meeting transcript and vectors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 text-[11px] text-neutral-500 pt-1 border-t border-neutral-100">
                        <span className="flex items-center gap-1">
                          <Layers className="w-3 h-3 text-neutral-400" />
                          <span>384d Vector Embeddings Active</span>
                        </span>
                        <span className="flex items-center gap-1">
                          <Shield className="w-3 h-3 text-neutral-400" />
                          <span>Untrusted Source Evidence</span>
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {/* Modal: Create Knowledge Note */}
      {isCreateNoteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-xl border border-neutral-200 p-5 sm:p-6 max-w-lg w-full shadow-lg space-y-4 max-h-[90vh] overflow-y-auto animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-neutral-100 pb-3">
              <h3 className="text-sm font-semibold text-neutral-900 flex items-center gap-2">
                <FileText className="w-4 h-4 text-neutral-700" />
                <span>Create Personal Knowledge Note</span>
              </h3>
              <button
                type="button"
                onClick={() => setIsCreateNoteModalOpen(false)}
                className="text-neutral-400 hover:text-neutral-600 text-xs font-mono"
              >
                ✕
              </button>
            </div>

            {noteError && (
              <div className="p-2.5 rounded bg-rose-50 border border-rose-200 text-xs text-rose-700">
                {noteError}
              </div>
            )}

            <form onSubmit={handleCreateNote} className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">
                  Title
                </label>
                <input
                  type="text"
                  required
                  value={noteTitle}
                  onChange={(e) => setNoteTitle(e.target.value)}
                  placeholder="e.g. Rationale for gRPC migration in Payments"
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">
                  Markdown Content
                </label>
                <textarea
                  required
                  rows={5}
                  value={noteContent}
                  onChange={(e) => setNoteContent(e.target.value)}
                  placeholder="Detail context, decisions, caveats, or trade-offs..."
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900 font-sans"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">
                  Optional Linked Record IDs (comma separated UUIDs)
                </label>
                <input
                  type="text"
                  value={noteRecordIds}
                  onChange={(e) => setNoteRecordIds(e.target.value)}
                  placeholder="e.g. 550e8400-e29b-41d4-a716-446655440000"
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900 font-mono"
                />
                <span className="text-[10px] text-neutral-400 block">
                  Backend validates that your identity has source access to every linked record.
                </span>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsCreateNoteModalOpen(false)}
                  className="px-3 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingNote}
                  className="px-4 py-1.5 text-xs font-medium bg-neutral-900 text-white rounded-lg hover:bg-neutral-800 disabled:opacity-50"
                >
                  {isSubmittingNote ? "Creating Note..." : "Save Note"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Ingest Meeting Transcript */}
      {isIngestMeetingModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/40 backdrop-blur-xs p-4">
          <div className="bg-white rounded-xl border border-neutral-200 p-5 sm:p-6 max-w-lg w-full shadow-lg space-y-4 max-h-[90vh] overflow-y-auto animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between border-b border-neutral-100 pb-3">
              <h3 className="text-sm font-semibold text-neutral-900 flex items-center gap-2">
                <Calendar className="w-4 h-4 text-neutral-700" />
                <span>Ingest Meeting Transcript</span>
              </h3>
              <button
                type="button"
                onClick={() => setIsIngestMeetingModalOpen(false)}
                className="text-neutral-400 hover:text-neutral-600 text-xs font-mono"
              >
                ✕
              </button>
            </div>

            {meetingError && (
              <div className="p-2.5 rounded bg-rose-50 border border-rose-200 text-xs text-rose-700">
                {meetingError}
              </div>
            )}

            <form onSubmit={handleIngestMeeting} className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">
                  Meeting Title
                </label>
                <input
                  type="text"
                  required
                  value={meetingTitle}
                  onChange={(e) => setMeetingTitle(e.target.value)}
                  placeholder="e.g. Payments Architecture Sync - Q3"
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">
                  Meeting Date (Optional)
                </label>
                <input
                  type="date"
                  value={meetingDate}
                  onChange={(e) => setMeetingDate(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-neutral-700 block">
                  Transcript or Notes (min 10 characters)
                </label>
                <textarea
                  required
                  rows={6}
                  value={meetingContent}
                  onChange={(e) => setMeetingContent(e.target.value)}
                  placeholder="Paste meeting transcript or notes..."
                  className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 focus:outline-hidden focus:ring-1 focus:ring-neutral-900 font-sans"
                />
                <span className="text-[10px] text-neutral-400 block">
                  Chunks and 384d vector embeddings are generated in-memory and committed in a single atomic transaction.
                </span>
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setIsIngestMeetingModalOpen(false)}
                  className="px-3 py-1.5 text-xs text-neutral-600 hover:bg-neutral-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingMeeting}
                  className="px-4 py-1.5 text-xs font-medium bg-neutral-900 text-white rounded-lg hover:bg-neutral-800 disabled:opacity-50"
                >
                  {isSubmittingMeeting ? "Computing Embeddings & Ingesting..." : "Ingest Transcript"}
                </button>
              </div>
            </form>
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
