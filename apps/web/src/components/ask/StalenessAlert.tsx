import React from "react";
import { AlertTriangle, Clock } from "lucide-react";

interface StalenessAlertProps {
  warning: string;
}

export function StalenessAlert({ warning }: StalenessAlertProps) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-200 bg-amber-50/60 p-4 text-amber-900 transition-colors"
    >
      <div className="flex items-start gap-3">
        <Clock className="w-5 h-5 text-amber-600 mt-0.5 shrink-0" aria-hidden="true" />
        <div className="flex-1 space-y-1">
          <div className="flex items-center gap-2">
            <h4 className="text-xs font-semibold tracking-wider uppercase text-amber-800">
              Subsequent Activity Detected
            </h4>
            <span className="inline-flex items-center gap-1 text-[11px] text-amber-700 font-medium">
              <AlertTriangle className="w-3 h-3" /> Historical Context
            </span>
          </div>
          <p className="text-sm text-amber-900/90 leading-relaxed font-normal">
            {warning}
          </p>
          <p className="text-xs text-amber-700/80 pt-1">
            Note: This advisory alerts you that later changes were synced. It does not declare the cited decision invalid.
          </p>
        </div>
      </div>
    </div>
  );
}

