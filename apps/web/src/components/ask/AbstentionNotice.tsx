import React from "react";
import { ShieldAlert, FileQuestion } from "lucide-react";

interface AbstentionNoticeProps {
  answerText: string;
  reason: string;
}

export function AbstentionNotice({ answerText, reason }: AbstentionNoticeProps) {
  return (
    <div
      role="region"
      aria-label="Abstention Notice"
      className="rounded-lg border border-stone-300 bg-stone-50/80 p-5 space-y-3"
    >
      <div className="flex items-center gap-2 text-stone-700">
        <FileQuestion className="w-5 h-5 text-stone-500" aria-hidden="true" />
        <h3 className="text-sm font-semibold tracking-wide text-stone-900 uppercase">
          Honest Abstention — Undocumented Rationale
        </h3>
      </div>

      <p className="text-sm text-stone-800 leading-relaxed font-normal">
        {answerText}
      </p>

      {reason && (
        <div className="rounded-md bg-white border border-stone-200 p-3 text-xs text-stone-600 flex items-start gap-2">
          <ShieldAlert className="w-4 h-4 text-stone-400 mt-0.5 shrink-0" aria-hidden="true" />
          <div>
            <span className="font-medium text-stone-700">Verification Finding: </span>
            {reason}
          </div>
        </div>
      )}

      <p className="text-xs text-stone-500 pt-1">
        Institutional Memory Agent strictly refrains from guessing or generating unverified rationale when primary engineering sources do not confirm the facts.
      </p>
    </div>
  );
}

