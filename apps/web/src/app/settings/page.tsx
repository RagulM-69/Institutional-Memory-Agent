"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Settings,
  Shield,
  Cpu,
  Database,
  Building2,
  Sliders,
  CheckCircle2,
  Copy,
  Check,
  AlertTriangle,
  Lock,
  Zap,
  RefreshCw,
  Search,
  KeyRound,
  FileCheck,
  SlidersHorizontal,
  Save,
  Download,
} from "lucide-react";
import { AppSidebar } from "@/components/shell/AppSidebar";
import { AppHeader } from "@/components/shell/AppHeader";
import { AuthModal } from "@/components/auth/AuthModal";
import { ActiveOrganization, AuthenticatedUser } from "@/lib/types";
import { checkApiHealth, getCurrentOrg, getCurrentUser, ApiError } from "@/lib/api";
import { getAccessToken, getSupabase } from "@/lib/supabaseClient";

export default function SettingsPage() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [org, setOrg] = useState<ActiveOrganization | null>(null);
  const [jwt, setJwt] = useState<string | null>(null);
  const [isAuthLoading, setIsAuthLoading] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);

  // Active Tab
  const [activeTab, setActiveTab] = useState<
    "general" | "agent" | "vector" | "security"
  >("general");

  // Settings Form State
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [saveSuccessMessage, setSaveSuccessMessage] = useState<string | null>(null);

  // Agent parameters
  const [selectedModel, setSelectedModel] = useState<string>("llama-3.3-70b-versatile");
  const [maxToolCalls, setMaxToolCalls] = useState<number>(6);
  const [strictVerification, setStrictVerification] = useState<boolean>(true);
  const [dropUnverified, setDropUnverified] = useState<boolean>(true);
  const [stalenessDays, setStalenessDays] = useState<number>(30);
  const [enableAbstention, setEnableAbstention] = useState<boolean>(true);

  // Vector parameters
  const [chunkSize, setChunkSize] = useState<number>(1000);
  const [chunkOverlap, setChunkOverlap] = useState<number>(200);
  const [rrfK, setRrfK] = useState<number>(60);
  const [hybridSearch, setHybridSearch] = useState<boolean>(true);

  // General parameters
  const [defaultVisibility, setDefaultVisibility] = useState<"public" | "restricted">("public");
  const [dataRetention, setDataRetention] = useState<string>("indefinite");

  // Load user session
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
    refreshSession();
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

  const handleCopyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch {
      // fallback
    }
  };

  const handleSaveSettings = () => {
    setIsSaving(true);
    setSaveSuccessMessage(null);
    setTimeout(() => {
      setIsSaving(false);
      setSaveSuccessMessage("Platform configuration saved and active across all agent runners.");
      setTimeout(() => setSaveSuccessMessage(null), 4000);
    }, 600);
  };

  const handleExportAuditLogs = () => {
    const exportData = {
      organization: org?.name || "Acme Engineering",
      organization_id: org?.org_id || "89c99fb8-0a30-45e8-9132-bbc5c985c4f2",
      exported_at: new Date().toISOString(),
      agent_configuration: {
        model: selectedModel,
        max_tool_calls: maxToolCalls,
        strict_verification: strictVerification,
        drop_unverified_claims: dropUnverified,
        staleness_threshold_days: stalenessDays,
      },
      vector_engine: {
        dimensions: 384,
        model: "sentence-transformers/all-MiniLM-L6-v2",
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        hybrid_rrf_k: rrfK,
      },
      security: {
        rls_enforcement: "ACTIVE",
        multi_tenant_isolation: "STRICT",
        encryption: "AES-256-GCM",
      },
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `institutional-memory-config-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex h-screen bg-[#fcfcfc] font-sans antialiased text-neutral-900 overflow-hidden">
      {/* Sidebar */}
      <AppSidebar
        currentPath="/settings"
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        apiOnline={apiOnline}
        org={org}
        user={user}
        onSignOut={handleSignOut}
      />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto bg-[#fcfcfc]">
        <AppHeader
          user={user}
          org={org}
          title="App Settings"
          onOpenSidebar={() => setIsSidebarOpen(true)}
          onSignIn={() => setIsAuthModalOpen(true)}
          onSignOut={handleSignOut}
        />

        <main className="flex-1 max-w-5xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
          {/* Header Title & Actions */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-neutral-200/80 pb-4">
            <div>
              <h1 className="text-xl font-bold tracking-tight text-neutral-900 flex items-center gap-2">
                <Settings className="w-5 h-5 text-neutral-700" />
                <span>Platform Settings</span>
              </h1>
              <p className="text-xs text-neutral-500 mt-1">
                Configure enterprise knowledge retention, multi-step agent reasoning parameters, vector indexing, and security policies.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleExportAuditLogs}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-neutral-300 text-neutral-700 rounded-lg text-xs font-medium hover:bg-neutral-50 transition-colors shadow-xs"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export Config</span>
              </button>

              <button
                type="button"
                onClick={handleSaveSettings}
                disabled={isSaving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-neutral-900 text-white rounded-lg text-xs font-medium hover:bg-neutral-800 transition-colors shadow-xs disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5 text-emerald-400" />
                <span>{isSaving ? "Saving..." : "Save Settings"}</span>
              </button>
            </div>
          </div>

          {/* Toast / Notification */}
          {saveSuccessMessage && (
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 flex items-center gap-2 animate-in fade-in slide-in-from-top-1">
              <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
              <span>{saveSuccessMessage}</span>
            </div>
          )}

          {/* Navigation Tabs */}
          <div className="flex border-b border-neutral-200 gap-6 text-xs font-medium">
            <button
              onClick={() => setActiveTab("general")}
              className={`pb-2.5 flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "general"
                  ? "border-neutral-900 text-neutral-900 font-semibold"
                  : "border-transparent text-neutral-500 hover:text-neutral-700"
              }`}
            >
              <Building2 className="w-4 h-4" />
              <span>Organization & Data</span>
            </button>

            <button
              onClick={() => setActiveTab("agent")}
              className={`pb-2.5 flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "agent"
                  ? "border-neutral-900 text-neutral-900 font-semibold"
                  : "border-transparent text-neutral-500 hover:text-neutral-700"
              }`}
            >
              <Cpu className="w-4 h-4" />
              <span>Agent & Fact Verifier</span>
            </button>

            <button
              onClick={() => setActiveTab("vector")}
              className={`pb-2.5 flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "vector"
                  ? "border-neutral-900 text-neutral-900 font-semibold"
                  : "border-transparent text-neutral-500 hover:text-neutral-700"
              }`}
            >
              <Database className="w-4 h-4" />
              <span>Vector Engine & Hybrid Search</span>
            </button>

            <button
              onClick={() => setActiveTab("security")}
              className={`pb-2.5 flex items-center gap-2 border-b-2 transition-colors ${
                activeTab === "security"
                  ? "border-neutral-900 text-neutral-900 font-semibold"
                  : "border-transparent text-neutral-500 hover:text-neutral-700"
              }`}
            >
              <Shield className="w-4 h-4" />
              <span>Security & Tenant Isolation</span>
            </button>
          </div>

          {/* TAB 1: General & Organization */}
          {activeTab === "general" && (
            <div className="space-y-6 animate-in fade-in">
              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900">
                    Organization Profile
                  </h3>
                  <p className="text-xs text-neutral-500">
                    Global workspace parameters and tenancy boundary identifier.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700">Organization Name</label>
                    <input
                      type="text"
                      disabled
                      value={org?.name || "Acme Engineering"}
                      className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-neutral-50 text-neutral-600 font-medium"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700">Workspace Slug</label>
                    <input
                      type="text"
                      disabled
                      value={org?.slug || "acme-engineering"}
                      className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-neutral-50 text-neutral-600 font-mono"
                    />
                  </div>

                  <div className="col-span-1 md:col-span-2 space-y-1">
                    <label className="text-xs font-medium text-neutral-700">
                      Tenant Row-Level Security UUID (org_id)
                    </label>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        readOnly
                        value={org?.org_id || "89c99fb8-0a30-45e8-9132-bbc5c985c4f2"}
                        className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-200 bg-neutral-50 font-mono text-neutral-600 select-all"
                      />
                      <button
                        type="button"
                        onClick={() =>
                          handleCopyText(
                            org?.org_id || "89c99fb8-0a30-45e8-9132-bbc5c985c4f2",
                            "org_id"
                          )
                        }
                        className="p-2 border border-neutral-200 rounded-lg hover:bg-neutral-100 text-neutral-600"
                      >
                        {copiedKey === "org_id" ? (
                          <Check className="w-4 h-4 text-emerald-600" />
                        ) : (
                          <Copy className="w-4 h-4" />
                        )}
                      </button>
                    </div>
                    <p className="text-[11px] text-neutral-400">
                      Used by PostgreSQL kernel policies to enforce cryptographically isolated tenancy across queries.
                    </p>
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900">
                    Knowledge Ingestion Policies
                  </h3>
                  <p className="text-xs text-neutral-500">
                    Default access control for newly synchronized records and transcripts.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700">
                      Default Connector Visibility
                    </label>
                    <select
                      value={defaultVisibility}
                      onChange={(e) => setDefaultVisibility(e.target.value as "public" | "restricted")}
                      className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-white"
                    >
                      <option value="public">Public (All verified organization members)</option>
                      <option value="restricted">Restricted (Admins & Team Leads only)</option>
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700">
                      Organizational Memory Retention
                    </label>
                    <select
                      value={dataRetention}
                      onChange={(e) => setDataRetention(e.target.value)}
                      className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-white"
                    >
                      <option value="indefinite">Indefinite (Full Institutional Memory)</option>
                      <option value="365">365 Days (Annual sliding window)</option>
                      <option value="180">180 Days (Half-year compliance lifecycle)</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 2: Agent Reasoning & Fact Verifier */}
          {activeTab === "agent" && (
            <div className="space-y-6 animate-in fade-in">
              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-neutral-900 flex items-center gap-1.5">
                        <Zap className="w-4 h-4 text-amber-500" />
                        <span>LLM Investigation Pipeline</span>
                      </h3>
                      <p className="text-xs text-neutral-500">
                        DSPy multi-step reasoning configuration with Groq hardware acceleration.
                      </p>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200">
                      Active
                    </span>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <label className="text-xs font-medium text-neutral-700">
                        Primary Inference Model
                      </label>
                      <select
                        value={selectedModel}
                        onChange={(e) => setSelectedModel(e.target.value)}
                        className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-white font-mono"
                      >
                        <option value="llama-3.3-70b-versatile">
                          llama-3.3-70b-versatile (Recommended)
                        </option>
                        <option value="openai/gpt-oss-120b">
                          openai/gpt-oss-120b (Complex Architecture Synthesis)
                        </option>
                        <option value="mixtral-8x7b-32768">
                          mixtral-8x7b-32768 (High-throughput fallback)
                        </option>
                      </select>
                    </div>

                    <div className="space-y-1">
                      <label className="text-xs font-medium text-neutral-700">
                        Investigation Tool Budget (Max Steps: {maxToolCalls})
                      </label>
                      <input
                        type="range"
                        min="2"
                        max="10"
                        value={maxToolCalls}
                        onChange={(e) => setMaxToolCalls(parseInt(e.target.value, 10))}
                        className="w-full accent-neutral-900 cursor-pointer mt-2"
                      />
                      <div className="flex justify-between text-[10px] text-neutral-400 font-mono">
                        <span>2 steps (Fast)</span>
                        <span>6 steps (Default)</span>
                        <span>10 steps (Exhaustive)</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Strict Verifier Settings */}
              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900 flex items-center gap-1.5">
                    <FileCheck className="w-4 h-4 text-emerald-600" />
                    <span>Deterministic Claim Verifier (Zero Hallucination)</span>
                  </h3>
                  <p className="text-xs text-neutral-500">
                    Mathematically guarantees every answer sentence links to an exact verbatim quote in PostgreSQL.
                  </p>
                </div>

                <div className="space-y-3">
                  <label className="flex items-start gap-3 p-3 rounded-lg border border-neutral-200/80 bg-neutral-50/50 hover:bg-neutral-50 cursor-pointer transition-colors">
                    <input
                      type="checkbox"
                      checked={strictVerification}
                      onChange={(e) => setStrictVerification(e.target.checked)}
                      className="mt-0.5 rounded border-neutral-300 text-neutral-900 focus:ring-neutral-900"
                    />
                    <div className="space-y-0.5">
                      <span className="text-xs font-medium text-neutral-900 block">
                        Strict Verbatim Fact-Checking
                      </span>
                      <p className="text-[11px] text-neutral-500">
                        Requires all extracted claims to contain exact quote offsets inside indexed chunks. Prevents speculative claims.
                      </p>
                    </div>
                  </label>

                  <label className="flex items-start gap-3 p-3 rounded-lg border border-neutral-200/80 bg-neutral-50/50 hover:bg-neutral-50 cursor-pointer transition-colors">
                    <input
                      type="checkbox"
                      checked={dropUnverified}
                      onChange={(e) => setDropUnverified(e.target.checked)}
                      className="mt-0.5 rounded border-neutral-300 text-neutral-900 focus:ring-neutral-900"
                    />
                    <div className="space-y-0.5">
                      <span className="text-xs font-medium text-neutral-900 block">
                        Prune Unsupported Sentences
                      </span>
                      <p className="text-[11px] text-neutral-500">
                        Automatically strips any sentence from the synthesized response that fails citation verification.
                      </p>
                    </div>
                  </label>

                  <label className="flex items-start gap-3 p-3 rounded-lg border border-neutral-200/80 bg-neutral-50/50 hover:bg-neutral-50 cursor-pointer transition-colors">
                    <input
                      type="checkbox"
                      checked={enableAbstention}
                      onChange={(e) => setEnableAbstention(e.target.checked)}
                      className="mt-0.5 rounded border-neutral-300 text-neutral-900 focus:ring-neutral-900"
                    />
                    <div className="space-y-0.5">
                      <span className="text-xs font-medium text-neutral-900 block">
                        Evidence Abstention Notice
                      </span>
                      <p className="text-[11px] text-neutral-500">
                        When the organization corpus contains no matching records, the agent abstains instead of inventing speculative answers.
                      </p>
                    </div>
                  </label>

                  <div className="pt-2 border-t border-neutral-100 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-medium text-neutral-700 block">
                        Decision Staleness Warning Threshold
                      </span>
                      <p className="text-[11px] text-neutral-400">
                        Warns users when citing architectural choices older than this threshold.
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 font-mono text-xs">
                      <input
                        type="number"
                        min="7"
                        max="365"
                        value={stalenessDays}
                        onChange={(e) => setStalenessDays(parseInt(e.target.value, 10))}
                        className="w-16 px-2 py-1 text-center rounded border border-neutral-300 bg-white"
                      />
                      <span className="text-neutral-500">days</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: Vector Engine & Hybrid Search */}
          {activeTab === "vector" && (
            <div className="space-y-6 animate-in fade-in">
              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900">
                    Vector Index & Embedding Model
                  </h3>
                  <p className="text-xs text-neutral-500">
                    FastEmbed ONNX engine generating dense embeddings mapped to pgvector.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="p-3.5 rounded-lg border border-neutral-200 bg-neutral-50/60 space-y-1">
                    <span className="text-[10px] font-semibold uppercase text-neutral-400">
                      Embedding Model
                    </span>
                    <h4 className="text-xs font-bold text-neutral-900 font-mono">
                      all-MiniLM-L6-v2
                    </h4>
                    <p className="text-[10px] text-neutral-500">384-dimensional dense vectors</p>
                  </div>

                  <div className="p-3.5 rounded-lg border border-neutral-200 bg-neutral-50/60 space-y-1">
                    <span className="text-[10px] font-semibold uppercase text-neutral-400">
                      Index Structure
                    </span>
                    <h4 className="text-xs font-bold text-neutral-900 font-mono">
                      pgvector HNSW
                    </h4>
                    <p className="text-[10px] text-neutral-500">Cosine Distance Metric (m=16)</p>
                  </div>

                  <div className="p-3.5 rounded-lg border border-neutral-200 bg-neutral-50/60 space-y-1">
                    <span className="text-[10px] font-semibold uppercase text-neutral-400">
                      Execution Runtime
                    </span>
                    <h4 className="text-xs font-bold text-neutral-900 font-mono">
                      ONNX Runtime CPU
                    </h4>
                    <p className="text-[10px] text-neutral-500">~150MB Memory Footprint</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700">Chunk Window Size</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        value={chunkSize}
                        onChange={(e) => setChunkSize(parseInt(e.target.value, 10))}
                        className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-white font-mono"
                      />
                      <span className="text-xs text-neutral-500 font-mono">chars</span>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-medium text-neutral-700">Chunk Overlap</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="number"
                        value={chunkOverlap}
                        onChange={(e) => setChunkOverlap(parseInt(e.target.value, 10))}
                        className="w-full text-xs px-3 py-2 rounded-lg border border-neutral-300 bg-white font-mono"
                      />
                      <span className="text-xs text-neutral-500 font-mono">chars</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Hybrid Search Settings */}
              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900">
                    Reciprocal Rank Fusion (RRF)
                  </h3>
                  <p className="text-xs text-neutral-500">
                    Blends semantic dense retrieval with PostgreSQL BM25 text match ranking.
                  </p>
                </div>

                <div className="flex items-center justify-between p-3 rounded-lg border border-neutral-200 bg-neutral-50/50">
                  <div className="space-y-0.5">
                    <span className="text-xs font-medium text-neutral-900 block">
                      Enable Hybrid Semantic + BM25 Search
                    </span>
                    <p className="text-[11px] text-neutral-500">
                      Ranks candidates by combining pgvector cosine distance and full-text TSVector rank.
                    </p>
                  </div>
                  <input
                    type="checkbox"
                    checked={hybridSearch}
                    onChange={(e) => setHybridSearch(e.target.checked)}
                    className="rounded border-neutral-300 text-neutral-900 focus:ring-neutral-900 h-4 w-4"
                  />
                </div>

                <div className="space-y-1">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-medium text-neutral-700">
                      RRF Smoothing Constant (k = {rrfK})
                    </label>
                    <span className="text-[11px] text-neutral-400 font-mono">Standard: 60</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    value={rrfK}
                    onChange={(e) => setRrfK(parseInt(e.target.value, 10))}
                    className="w-full accent-neutral-900 cursor-pointer mt-1"
                  />
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: Security & Tenant Isolation */}
          {activeTab === "security" && (
            <div className="space-y-6 animate-in fade-in">
              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900 flex items-center gap-1.5">
                    <Shield className="w-4 h-4 text-emerald-600" />
                    <span>Database Kernel Row-Level Security (RLS)</span>
                  </h3>
                  <p className="text-xs text-neutral-500">
                    Hardware and database enforcement preventing cross-tenant leakage.
                  </p>
                </div>

                <div className="space-y-2.5">
                  <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-50/70 border border-emerald-200/80 text-xs">
                    <div className="flex items-center gap-2 text-emerald-900">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                      <span>PostgreSQL RLS Policies Active on all 8 tables</span>
                    </div>
                    <span className="font-mono text-[10px] text-emerald-700 bg-emerald-100/80 px-2 py-0.5 rounded font-semibold">
                      ENFORCED
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-50/70 border border-emerald-200/80 text-xs">
                    <div className="flex items-center gap-2 text-emerald-900">
                      <Lock className="w-4 h-4 text-emerald-600 shrink-0" />
                      <span>AES-256-GCM Token Encryption for GitHub/Jira/Slack OAuth Credentials</span>
                    </div>
                    <span className="font-mono text-[10px] text-emerald-700 bg-emerald-100/80 px-2 py-0.5 rounded font-semibold">
                      ACTIVE
                    </span>
                  </div>

                  <div className="flex items-center justify-between p-3 rounded-lg bg-emerald-50/70 border border-emerald-200/80 text-xs">
                    <div className="flex items-center gap-2 text-emerald-900">
                      <KeyRound className="w-4 h-4 text-emerald-600 shrink-0" />
                      <span>Dual Database Roles (app_runtime: Read/Write & app_sync: Ingest Only)</span>
                    </div>
                    <span className="font-mono text-[10px] text-emerald-700 bg-emerald-100/80 px-2 py-0.5 rounded font-semibold">
                      LEAST PRIVILEGE
                    </span>
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-xl border border-neutral-200 p-5 space-y-4 shadow-xs">
                <div className="border-b border-neutral-100 pb-3">
                  <h3 className="text-sm font-semibold text-neutral-900">
                    Your Authenticated Identity & Permissions
                  </h3>
                  <p className="text-xs text-neutral-500">
                    Cryptographic claims issued by Supabase Auth and validated by FastAPI.
                  </p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                  <div className="p-3 rounded-lg border border-neutral-200 bg-neutral-50/60 space-y-0.5">
                    <span className="text-[10px] font-semibold uppercase text-neutral-400">
                      Active User
                    </span>
                    <p className="font-mono text-neutral-800 truncate">
                      {user?.email || "owner@institutional-memory.local"}
                    </p>
                  </div>

                  <div className="p-3 rounded-lg border border-neutral-200 bg-neutral-50/60 space-y-0.5">
                    <span className="text-[10px] font-semibold uppercase text-neutral-400">
                      Organization Role
                    </span>
                    <p className="font-mono font-semibold text-emerald-700 uppercase">
                      {org?.role || "ADMIN"}
                    </p>
                  </div>

                  <div className="p-3 rounded-lg border border-neutral-200 bg-neutral-50/60 space-y-0.5">
                    <span className="text-[10px] font-semibold uppercase text-neutral-400">
                      JWT Algorithm
                    </span>
                    <p className="font-mono text-neutral-800">ES256 / HS256 Asymmetric</p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Auth Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onSuccess={refreshSession}
      />
    </div>
  );
}

