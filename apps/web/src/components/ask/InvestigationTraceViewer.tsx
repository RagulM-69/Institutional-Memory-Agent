import React, { useState } from "react";
import { ChevronDown, ChevronRight, Activity, CheckCircle2, Clock } from "lucide-react";
import { AskMetrics, InvestigationTraceStep } from "@/lib/types";

interface InvestigationTraceViewerProps {
  trace: InvestigationTraceStep[];
  metrics: AskMetrics;
}

export function InvestigationTraceViewer({
  trace,
  metrics,
}: InvestigationTraceViewerProps) {
  const [isOpen, setIsOpen] = useState<boolean>(false);

  if (!trace || trace.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-neutral-50/50 text-xs">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3.5 text-left font-medium text-neutral-700 hover:text-neutral-900 transition-colors"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-neutral-500" />
          <span className="font-semibold text-neutral-800">
            Investigation Audit Trace
          </span>
          <span className="text-[11px] font-normal text-neutral-500">
            ({trace.length} verified steps • {metrics.duration_seconds ?? 0}s)
          </span>
        </div>

        <div className="flex items-center gap-2 text-neutral-500">
          <span className="text-[11px] uppercase tracking-wider font-semibold">
            {isOpen ? "Hide Trace" : "View Trace"}
          </span>
          {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </button>

      {isOpen && (
        <div className="p-3.5 pt-0 space-y-3 border-t border-neutral-200/80">
          {/* Metrics summary banner */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-3">
            <div className="p-2 bg-white rounded border border-neutral-200">
              <span className="text-[10px] text-neutral-400 uppercase tracking-wider block">Tool Calls</span>
              <span className="font-mono font-medium text-neutral-800 text-xs">{metrics.tool_calls ?? 0}</span>
            </div>
            <div className="p-2 bg-white rounded border border-neutral-200">
              <span className="text-[10px] text-neutral-400 uppercase tracking-wider block">Evidence Chunks</span>
              <span className="font-mono font-medium text-neutral-800 text-xs">{metrics.retrieved_chunks_count ?? 0}</span>
            </div>
            <div className="p-2 bg-white rounded border border-neutral-200">
              <span className="text-[10px] text-neutral-400 uppercase tracking-wider block">Verified Claims</span>
              <span className="font-mono font-medium text-neutral-800 text-xs">{metrics.verified_claims_count ?? 0}</span>
            </div>
            <div className="p-2 bg-white rounded border border-neutral-200">
              <span className="text-[10px] text-neutral-400 uppercase tracking-wider block">Latency</span>
              <span className="font-mono font-medium text-neutral-800 text-xs">{metrics.duration_seconds ?? 0}s</span>
            </div>
          </div>

          {/* Trace steps */}
          <div className="space-y-2 pt-1 font-mono text-[11px]">
            {trace.map((step, idx) => (
              <div
                key={idx}
                className="p-2.5 rounded bg-white border border-neutral-200/90 text-neutral-700 space-y-1"
              >
                <div className="flex items-center justify-between text-neutral-500 text-[10px]">
                  <span className="font-bold text-neutral-700 uppercase tracking-wider">
                    Step {step.step}: {step.action}
                  </span>
                  {typeof step.duration_ms === "number" && (
                    <span className="flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {step.duration_ms}ms
                    </span>
                  )}
                </div>

                {step.query && (
                  <div className="text-neutral-900 font-sans">
                    <span className="text-neutral-400 font-mono">query: </span>
                    &ldquo;{step.query}&rdquo;
                  </div>
                )}

                {typeof step.results_count === "number" && (
                  <div className="text-neutral-600">
                    Retrieved {step.results_count} matching evidence chunks.
                  </div>
                )}

                {step.model && (
                  <div className="text-neutral-600">
                    Model: {step.model}
                  </div>
                )}

                {typeof step.verified_claims_count === "number" && (
                  <div className="text-emerald-700 flex items-center gap-1 font-sans">
                    <CheckCircle2 className="w-3 h-3 shrink-0" />
                    Verified {step.verified_claims_count} claim(s) with exact verbatim quotes
                    {step.unsupported_claims_count ? ` (${step.unsupported_claims_count} unverified claim(s) dropped)` : ""}
                  </div>
                )}

                {step.error && (
                  <div className="text-rose-600">
                    Error: {step.error}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
