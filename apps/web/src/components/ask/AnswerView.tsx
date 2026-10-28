import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  Copy,
  Check,
  RefreshCw,
  FileText,
  AlertCircle,
  ThumbsUp,
  ThumbsDown,
  MessageSquare,
  Sparkles,
  Share2,
} from "lucide-react";
import { AskResponse } from "@/lib/types";
import { submitAnswerFeedback } from "@/lib/api";
import { EvidenceBadge } from "./EvidenceBadge";
import { StalenessAlert } from "./StalenessAlert";
import { AbstentionNotice } from "./AbstentionNotice";
import { ClaimCard } from "./ClaimCard";
import { InvestigationTraceViewer } from "./InvestigationTraceViewer";

interface AnswerViewProps {
  response: AskResponse;
  onReset: () => void;
  jwt?: string | null;
  orgId?: string | null;
}

export function AnswerView({ response, onReset, jwt, orgId }: AnswerViewProps) {
  const [copied, setCopied] = useState<boolean>(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  // Feedback State
  const [selectedRating, setSelectedRating] = useState<1 | -1 | null>(null);
  const [feedbackNotes, setFeedbackNotes] = useState<string>("");
  const [showNotesInput, setShowNotesInput] = useState<boolean>(false);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState<boolean>(false);
  const [feedbackSuccessMsg, setFeedbackSuccessMsg] = useState<string | null>(null);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);

  const handleCopy = async () => {
    try {
      if (!navigator.clipboard || !navigator.clipboard.writeText) {
        throw new Error("Clipboard API not supported in this browser context.");
      }
      await navigator.clipboard.writeText(response.answer);
      setCopied(true);
      setCopyError(null);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.warn("Failed to copy answer to clipboard:", err);
      setCopyError("Clipboard write failed. Please select and copy text manually.");
      setTimeout(() => setCopyError(null), 4000);
    }
  };

  const handleFeedback = async (rating: 1 | -1) => {
    if (!response.answer_id) return;
    if (!jwt) {
      setFeedbackError("Please sign in to submit feedback.");
      return;
    }

    setSelectedRating(rating);
    setShowNotesInput(true);
    setIsSubmittingFeedback(true);
    setFeedbackError(null);

    try {
      await submitAnswerFeedback(
        response.answer_id,
        { rating, notes: feedbackNotes.trim() || undefined },
        jwt,
        orgId || undefined
      );
      setFeedbackSuccessMsg("Feedback recorded. Thank you!");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to record feedback.";
      setFeedbackError(msg);
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  const handleSaveNotes = async () => {
    if (!response.answer_id || !selectedRating || !jwt) return;
    setIsSubmittingFeedback(true);
    setFeedbackError(null);
    try {
      await submitAnswerFeedback(
        response.answer_id,
        { rating: selectedRating, notes: feedbackNotes.trim() || undefined },
        jwt,
        orgId || undefined
      );
      setFeedbackSuccessMsg("Feedback and notes saved successfully.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to save notes.";
      setFeedbackError(msg);
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  // Strictly filter to verified claims
  const verifiedClaims = (response.claims || []).filter(
    (c) => c.verification_status === "verified"
  );

  return (
    <div className="space-y-6 animate-in fade-in duration-200">
      {/* Elevated Master Answer Card */}
      <div className="rounded-2xl border border-neutral-200/90 bg-white shadow-xs overflow-hidden">
        {/* Card Header */}
        <div className="p-6 bg-gradient-to-b from-neutral-50/70 to-white border-b border-neutral-100 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-neutral-400">
                <Sparkles className="w-3.5 h-3.5 text-neutral-500" />
                <span>Submitted Question</span>
              </div>
              <h1 className="text-lg sm:text-xl font-semibold text-neutral-900 tracking-tight leading-snug">
                {response.question}
              </h1>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <EvidenceBadge
                level={response.evidence_level}
                reason={response.evidence_reason}
                showReason={false}
              />
            </div>
          </div>

          {/* Staleness Warning if present */}
          {response.staleness_warning && (
            <StalenessAlert warning={response.staleness_warning} />
          )}
        </div>

        {/* Card Body: Verified Answer Presentation */}
        <div className="p-6 sm:p-7 space-y-5">
          {response.is_abstention ? (
            <AbstentionNotice
              answerText={response.answer}
              reason={response.evidence_reason}
            />
          ) : (
            <div className="space-y-4">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-neutral-400 flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-neutral-500" />
                <span>Verified Answer</span>
              </div>

              {/* Elevated Markdown Answer Body */}
              <div className="prose prose-neutral max-w-none text-neutral-800 leading-relaxed text-[15px]">
                <ReactMarkdown
                  components={{
                    p: ({ children }) => <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>,
                    strong: ({ children }) => (
                      <strong className="font-semibold text-neutral-900 bg-neutral-100/70 px-1 py-0.5 rounded">
                        {children}
                      </strong>
                    ),
                    ul: ({ children }) => <ul className="my-2.5 list-disc pl-5 space-y-1">{children}</ul>,
                    ol: ({ children }) => <ol className="my-2.5 list-decimal pl-5 space-y-1">{children}</ol>,
                    li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                    code: ({ children, className }) => {
                      const isBlock = Boolean(className);
                      if (isBlock) {
                        return (
                          <code className="block p-3 rounded-lg bg-neutral-900 text-neutral-100 font-mono text-xs overflow-x-auto my-2">
                            {children}
                          </code>
                        );
                      }
                      return (
                        <code className="px-1.5 py-0.5 rounded bg-neutral-100 font-mono text-[13px] text-neutral-800 border border-neutral-200/80">
                          {children}
                        </code>
                      );
                    },
                    blockquote: ({ children }) => (
                      <blockquote className="border-l-3 border-amber-400 pl-3 italic text-neutral-600 my-2">
                        {children}
                      </blockquote>
                    ),
                  }}
                >
                  {response.answer}
                </ReactMarkdown>
              </div>

              {response.evidence_reason && (
                <div className="rounded-lg bg-neutral-50 p-2.5 text-xs text-neutral-500 border border-neutral-200/70 flex items-center gap-2">
                  <span className="font-semibold text-neutral-700">Verification Status:</span>
                  <span>{response.evidence_reason}</span>
                </div>
              )}
            </div>
          )}

          {/* Action Toolbar */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-5 border-t border-neutral-100 text-xs text-neutral-600">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-neutral-200 hover:bg-neutral-50 text-neutral-700 font-medium transition-colors shadow-2xs"
                aria-label="Copy verified answer to clipboard"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                    <span className="text-emerald-700 font-medium">Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 text-neutral-500" />
                    <span>Copy Answer</span>
                  </>
                )}
              </button>

              {copyError && (
                <span className="text-rose-600 flex items-center gap-1 text-[11px] animate-in fade-in">
                  <AlertCircle className="w-3 h-3" />
                  {copyError}
                </span>
              )}
            </div>

            <button
              type="button"
              onClick={onReset}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-neutral-900 text-white hover:bg-neutral-800 font-medium transition-colors shadow-2xs"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Ask Another Question</span>
            </button>
          </div>

          {/* Answer Quality Feedback Section */}
          {response.answer_id && (
            <div className="pt-4 border-t border-neutral-100 space-y-2.5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
                <span className="text-neutral-500 font-medium">Was this verified answer accurate and helpful?</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={isSubmittingFeedback}
                    onClick={() => handleFeedback(1)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${
                      selectedRating === 1
                        ? "bg-emerald-50 text-emerald-800 border-emerald-300 shadow-2xs"
                        : "bg-white text-neutral-700 border-neutral-200 hover:bg-neutral-50"
                    }`}
                    aria-label="Accurate and helpful"
                  >
                    <ThumbsUp className="w-3.5 h-3.5 text-emerald-600" />
                    <span>Helpful (+1)</span>
                  </button>

                  <button
                    type="button"
                    disabled={isSubmittingFeedback}
                    onClick={() => handleFeedback(-1)}
                    className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border transition-colors ${
                      selectedRating === -1
                        ? "bg-rose-50 text-rose-800 border-rose-300 shadow-2xs"
                        : "bg-white text-neutral-700 border-neutral-200 hover:bg-neutral-50"
                    }`}
                    aria-label="Inaccurate or unhelpful"
                  >
                    <ThumbsDown className="w-3.5 h-3.5 text-rose-600" />
                    <span>Unhelpful (-1)</span>
                  </button>
                </div>
              </div>

              {feedbackSuccessMsg && (
                <p className="text-[11.5px] text-emerald-700 font-medium animate-in fade-in">
                  ✓ {feedbackSuccessMsg}
                </p>
              )}

              {feedbackError && (
                <p className="text-[11.5px] text-rose-600 font-medium animate-in fade-in">
                  ✗ {feedbackError}
                </p>
              )}

              {showNotesInput && (
                <div className="pt-2 space-y-2 animate-in fade-in duration-150">
                  <div className="flex items-center gap-1.5 text-[11px] text-neutral-500">
                    <MessageSquare className="w-3 h-3" />
                    <span>Optional notes or corrections for institutional memory:</span>
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={feedbackNotes}
                      onChange={(e) => setFeedbackNotes(e.target.value)}
                      placeholder="e.g. Citation was exact, but ticket KAN-3 had a later follow-up in Slack"
                      maxLength={2000}
                      className="flex-1 text-xs px-3 py-1.5 rounded-lg border border-neutral-200 focus:outline-hidden focus:ring-1 focus:ring-neutral-400 bg-neutral-50/50"
                    />
                    <button
                      type="button"
                      disabled={isSubmittingFeedback}
                      onClick={handleSaveNotes}
                      className="px-3 py-1.5 rounded-lg bg-neutral-800 text-white text-xs font-medium hover:bg-neutral-900 transition-colors disabled:opacity-50"
                    >
                      Save Notes
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Verified Citations Section */}
      {verifiedClaims.length > 0 && (
        <div className="space-y-3 pt-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-neutral-700" />
              <h2 className="text-sm font-semibold text-neutral-900 tracking-tight">
                Verified Evidence Citations ({verifiedClaims.length})
              </h2>
            </div>
            <span className="text-xs text-neutral-400 hidden sm:inline">
              Exact verbatim substrings verified against database records
            </span>
          </div>

          <div className="grid grid-cols-1 gap-3">
            {verifiedClaims.map((claim, idx) => (
              <ClaimCard key={idx} claim={claim} index={idx} />
            ))}
          </div>
        </div>
      )}

      {/* Investigation Audit Trace */}
      <InvestigationTraceViewer
        trace={response.investigation_trace}
        metrics={response.metrics}
      />
    </div>
  );
}
