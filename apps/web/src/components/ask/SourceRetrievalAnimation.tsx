"use client";

import React, { useEffect, useState } from "react";
import { GitHubLogo, JiraLogo, SlackLogo } from "@/components/common/BrandLogos";
import { Search, Database, CheckCircle2 } from "lucide-react";

interface SourceRetrievalAnimationProps {
  question: string;
}

const SEARCH_STAGES = [
  { text: "Scanning GitHub commits and pull request diffs...", source: "github" },
  { text: "Querying Jira issues, subtasks, and resolution statuses...", source: "jira" },
  { text: "Searching Slack architectural discussions in #handoff-discussion...", source: "slack" },
  { text: "Verifying exact quotes against primary records...", source: "verification" },
];

export function SourceRetrievalAnimation({ question }: SourceRetrievalAnimationProps) {
  const [stageIndex, setStageIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setStageIndex((prev) => (prev + 1) % SEARCH_STAGES.length);
    }, 1800);
    return () => clearInterval(timer);
  }, []);

  const currentStage = SEARCH_STAGES[stageIndex];

  return (
    <div className="rounded-2xl border border-neutral-200/90 bg-white p-6 sm:p-8 shadow-xs space-y-6 overflow-hidden relative">
      {/* Background ambient gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-neutral-50/60 via-transparent to-neutral-50/30 pointer-events-none" />

      {/* Query Banner */}
      <div className="relative space-y-1.5">
        <div className="flex items-center justify-between text-xs text-neutral-400 font-medium">
          <span className="uppercase tracking-wider text-[11px] font-semibold text-neutral-500 flex items-center gap-1.5">
            <Search className="w-3.5 h-3.5 text-neutral-600 animate-pulse" />
            Searching Across Integrated Sources
          </span>
          <span className="font-mono text-[11px] text-neutral-400">PostgreSQL · pgvector</span>
        </div>
        <p className="text-base sm:text-lg font-medium text-neutral-900 tracking-tight leading-snug">
          &ldquo;{question}&rdquo;
        </p>
      </div>

      {/* Global Status Bar with Scanning Beam */}
      <div className="relative rounded-xl bg-neutral-50 border border-neutral-200/70 p-3.5 overflow-hidden">
        <div className="flex items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="relative flex items-center justify-center w-5 h-5 shrink-0">
              <span className="absolute w-full h-full rounded-full bg-blue-400 animate-ping opacity-30" />
              <span className="relative w-2.5 h-2.5 rounded-full bg-blue-600" />
            </div>
            <span className="text-neutral-700 font-medium truncate font-sans text-[12.5px]">
              {currentStage.text}
            </span>
          </div>

          <div className="flex items-center gap-1.5 text-[11px] text-neutral-400 shrink-0 font-mono">
            <span>Retrieval Active</span>
          </div>
        </div>

        {/* High-tech Scanning Beam */}
        <div className="absolute bottom-0 left-0 right-0 h-[2px] bg-neutral-200/60 overflow-hidden">
          <div className="h-full w-1/3 bg-gradient-to-r from-transparent via-blue-500 to-transparent animate-scan-beam" />
        </div>
      </div>

      {/* Floating Animated Source Cards */}
      <div className="relative pt-2 pb-1">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {/* GitHub Source Card */}
          <div className="relative group rounded-xl border border-neutral-200/90 bg-white p-4.5 shadow-xs transition-all duration-300 animate-float-1 hover:border-neutral-400">
            {/* Ambient corner glow */}
            <div className="absolute top-0 right-0 w-24 h-24 bg-neutral-900/5 rounded-full blur-xl pointer-events-none" />

            <div className="space-y-3 relative">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-lg bg-neutral-900/10 animate-radar-pulse" />
                    <div className="w-8 h-8 rounded-lg bg-neutral-900 text-white flex items-center justify-center shadow-xs">
                      <GitHubLogo className="w-4 h-4 text-white" />
                    </div>
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold text-neutral-900">GitHub</h4>
                    <span className="block text-[11px] text-neutral-400 font-mono truncate max-w-[120px]">
                      Continuity
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200/60 text-[10px] font-medium text-emerald-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span>Searching</span>
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between text-[11px] text-neutral-500">
                  <span>Commits &amp; Diffs</span>
                  <span className="font-mono text-[10.5px] text-neutral-400">4 records</span>
                </div>
                {/* Live Scanning Line */}
                <div className="h-1.5 w-full bg-neutral-100 rounded-full overflow-hidden">
                  <div className="h-full w-2/5 bg-neutral-900 rounded-full animate-scan-beam" />
                </div>
                <p className="text-[11px] text-neutral-400 pt-0.5 font-mono">
                  Scanning commit history...
                </p>
              </div>
            </div>
          </div>

          {/* Jira Cloud Source Card */}
          <div className="relative group rounded-xl border border-neutral-200/90 bg-white p-4.5 shadow-xs transition-all duration-300 animate-float-2 hover:border-blue-300">
            {/* Ambient corner glow */}
            <div className="absolute top-0 right-0 w-24 h-24 bg-blue-500/5 rounded-full blur-xl pointer-events-none" />

            <div className="space-y-3 relative">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-lg bg-blue-500/15 animate-radar-pulse" />
                    <div className="w-8 h-8 rounded-lg bg-blue-50 border border-blue-200/80 flex items-center justify-center shadow-xs">
                      <JiraLogo className="w-4 h-4" />
                    </div>
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold text-neutral-900">Jira Cloud</h4>
                    <span className="block text-[11px] text-neutral-400 font-mono">
                      Project KAN
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200/60 text-[10px] font-medium text-emerald-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span>Searching</span>
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between text-[11px] text-neutral-500">
                  <span>Tasks &amp; Subtasks</span>
                  <span className="font-mono text-[10.5px] text-neutral-400">3 tickets</span>
                </div>
                {/* Live Scanning Line */}
                <div className="h-1.5 w-full bg-neutral-100 rounded-full overflow-hidden">
                  <div className="h-full w-2/5 bg-blue-600 rounded-full animate-scan-beam" />
                </div>
                <p className="text-[11px] text-neutral-400 pt-0.5 font-mono">
                  Scanning ticket state...
                </p>
              </div>
            </div>
          </div>

          {/* Slack Workspace Source Card */}
          <div className="relative group rounded-xl border border-neutral-200/90 bg-white p-4.5 shadow-xs transition-all duration-300 animate-float-3 hover:border-emerald-300">
            {/* Ambient corner glow */}
            <div className="absolute top-0 right-0 w-24 h-24 bg-emerald-500/5 rounded-full blur-xl pointer-events-none" />

            <div className="space-y-3 relative">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="relative flex items-center justify-center">
                    <span className="absolute w-8 h-8 rounded-lg bg-emerald-500/15 animate-radar-pulse" />
                    <div className="w-8 h-8 rounded-lg bg-emerald-50/70 border border-emerald-200/80 flex items-center justify-center shadow-xs">
                      <SlackLogo className="w-4 h-4" />
                    </div>
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold text-neutral-900">Slack</h4>
                    <span className="block text-[11px] text-neutral-400 font-mono truncate max-w-[120px]">
                      #handoff-discussion
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-50 border border-emerald-200/60 text-[10px] font-medium text-emerald-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  <span>Searching</span>
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex justify-between text-[11px] text-neutral-500">
                  <span>Channel Threads</span>
                  <span className="font-mono text-[10.5px] text-neutral-400">13 messages</span>
                </div>
                {/* Live Scanning Line */}
                <div className="h-1.5 w-full bg-neutral-100 rounded-full overflow-hidden">
                  <div className="h-full w-2/5 bg-emerald-600 rounded-full animate-scan-beam" />
                </div>
                <p className="text-[11px] text-neutral-400 pt-0.5 font-mono">
                  Scanning discussion threads...
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

