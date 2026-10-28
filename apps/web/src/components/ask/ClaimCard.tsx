import React, { useState } from "react";
import { ExternalLink, ChevronDown, ChevronUp, Quote, Check, Copy } from "lucide-react";
import { VerifiedClaim } from "@/lib/types";
import { BrandLogo } from "@/components/common/BrandLogos";

interface ClaimCardProps {
  claim: VerifiedClaim;
  index: number;
}

export function ClaimCard({ claim, index }: ClaimCardProps) {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);
  const [copied, setCopied] = useState<boolean>(false);

  // Map record types to recognizable labels and official brand logos
  const getSourceMeta = (type: string) => {
    const t = type.toLowerCase();
    if (t.includes("github") || t.includes("pull") || t.includes("pr") || t.includes("commit") || t.includes("review")) {
      return {
        label: "GitHub",
        brand: "github",
        badgeClass: "bg-neutral-900 text-white border-neutral-900",
        pillClass: "bg-neutral-100 text-neutral-800 border-neutral-200",
      };
    }
    if (t.includes("jira") || t.includes("issue")) {
      return {
        label: "Jira",
        brand: "jira",
        badgeClass: "bg-[#0052CC]/10 text-[#0052CC] border-[#0052CC]/20",
        pillClass: "bg-blue-50 text-blue-900 border-blue-200",
      };
    }
    if (t.includes("slack") || t.includes("chat") || t.includes("thread")) {
      return {
        label: "Slack",
        brand: "slack",
        badgeClass: "bg-emerald-50 text-emerald-800 border-emerald-200",
        pillClass: "bg-emerald-50 text-emerald-900 border-emerald-200",
      };
    }
    return {
      label: "Document",
      brand: "document",
      badgeClass: "bg-stone-100 text-stone-700 border-stone-200",
      pillClass: "bg-stone-50 text-stone-800 border-stone-200",
    };
  };

  const meta = getSourceMeta(claim.record_type || "");

  const handleCopyQuote = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(claim.exact_quote || claim.claim_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  };

  return (
    <div className="group rounded-xl border border-neutral-200/80 bg-white p-4.5 shadow-2xs hover:shadow-xs hover:border-neutral-300 transition-all duration-150">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2 flex-1 min-w-0">
          {/* Header pill & source meta */}
          <div className="flex items-center flex-wrap gap-2 text-xs">
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-neutral-100 text-neutral-700 font-mono font-semibold text-[11px] border border-neutral-200">
              {index + 1}
            </span>
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-[11.5px] font-medium border ${meta.pillClass}`}
            >
              <BrandLogo type={meta.brand} className="w-3.5 h-3.5 shrink-0" />
              <span>{meta.label}</span>
            </span>
            <span className="font-medium text-neutral-800 truncate max-w-md text-xs">
              {claim.record_title}
            </span>
          </div>

          {/* Claim assertion */}
          <p className="text-[13.5px] font-medium text-neutral-900 leading-snug">
            {claim.claim_text}
          </p>
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-1.5 shrink-0 pt-0.5">
          {claim.record_url && (
            <a
              href={claim.record_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium text-neutral-600 bg-neutral-50 hover:bg-neutral-100 hover:text-neutral-900 border border-neutral-200/80 transition-colors"
              title="Open primary engineering record upstream"
            >
              <ExternalLink className="w-3 h-3" />
              <span className="hidden sm:inline">Open</span>
            </a>
          )}

          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1 text-neutral-400 hover:text-neutral-700 hover:bg-neutral-100 rounded-md transition-colors"
            aria-label={isExpanded ? "Collapse verbatim citation" : "Expand verbatim citation"}
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Expanded Verbatim Quote Snippet */}
      {isExpanded && (
        <div className="mt-3 pt-3 border-t border-neutral-100 text-xs space-y-2 animate-in fade-in duration-150">
          <div className="flex items-center justify-between text-[11px] text-neutral-400">
            <span className="font-semibold uppercase tracking-wider text-neutral-500 flex items-center gap-1">
              <Quote className="w-3 h-3 text-amber-500" />
              Verbatim Evidence Quote
            </span>

            <button
              type="button"
              onClick={handleCopyQuote}
              className="inline-flex items-center gap-1 text-[11px] text-neutral-500 hover:text-neutral-900 transition-colors"
              title="Copy quote excerpt"
            >
              {copied ? (
                <>
                  <Check className="w-3 h-3 text-emerald-600" />
                  <span className="text-emerald-700 font-medium">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" />
                  <span>Copy</span>
                </>
              )}
            </button>
          </div>

          <div className="bg-amber-50/40 rounded-lg p-3 border border-amber-200/60 text-neutral-800 font-mono text-[11.5px] leading-relaxed relative">
            <p className="whitespace-pre-wrap select-all">
              &ldquo;{claim.exact_quote}&rdquo;
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
