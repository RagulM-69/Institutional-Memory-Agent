import React from "react";
import { CheckCircle2, HelpCircle, Lightbulb } from "lucide-react";
import { EvidenceLevel } from "@/lib/types";

interface EvidenceBadgeProps {
  level: EvidenceLevel;
  reason?: string;
  showReason?: boolean;
  className?: string;
}

export function EvidenceBadge({
  level,
  reason,
  showReason = false,
  className = "",
}: EvidenceBadgeProps) {
  const configs = {
    documented: {
      label: "Documented",
      icon: CheckCircle2,
      badgeClass: "bg-emerald-50 text-emerald-800 border-emerald-200",
      dotClass: "bg-emerald-500",
      description: "Directly verified by exact quotes from primary records.",
    },
    inferred: {
      label: "Inferred",
      icon: Lightbulb,
      badgeClass: "bg-sky-50 text-sky-800 border-sky-200",
      dotClass: "bg-sky-500",
      description: "Synthesized through logical deduction from verified records.",
    },
    unknown: {
      label: "Unknown / Abstention",
      icon: HelpCircle,
      badgeClass: "bg-stone-100 text-stone-800 border-stone-200",
      dotClass: "bg-stone-500",
      description: "Institutional records do not establish or confirm this rationale.",
    },
  };

  const config = configs[level] || configs.unknown;
  const Icon = config.icon;

  return (
    <div className={`inline-flex flex-col gap-1 ${className}`}>
      <span
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border ${config.badgeClass}`}
        title={config.description}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${config.dotClass}`} />
        <Icon className="w-3.5 h-3.5" />
        <span className="tracking-wide uppercase text-[11px] font-semibold">{config.label}</span>
      </span>

      {showReason && reason && (
        <p className="text-xs text-neutral-600 mt-1 italic leading-relaxed">
          {reason}
        </p>
      )}
    </div>
  );
}

