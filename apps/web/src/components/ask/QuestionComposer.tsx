"use client";

import React, { useState, useRef, useEffect } from "react";
import { Search, Loader2 } from "lucide-react";

interface QuestionComposerProps {
  onSubmit: (question: string) => void;
  isLoading: boolean;
  disabled?: boolean;
}

export function QuestionComposer({
  onSubmit,
  isLoading,
  disabled = false,
}: QuestionComposerProps) {
  const [question, setQuestion] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea height as content changes
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        220
      )}px`;
    }
  }, [question]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isLoading || disabled || !question.trim()) return;
    onSubmit(question.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="w-full">
      <form
        onSubmit={handleSubmit}
        className="relative rounded-2xl border border-neutral-300 bg-white shadow-xs focus-within:border-neutral-500 focus-within:ring-1 focus-within:ring-neutral-400 transition-all"
      >
        <label htmlFor="question-input" className="sr-only">
          Engineering Search
        </label>
        <textarea
          id="question-input"
          ref={textareaRef}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search technical decisions, why an architecture or library was chosen, or system history..."
          disabled={isLoading || disabled}
          rows={3}
          className="w-full resize-none bg-transparent px-5 pt-4 pb-14 text-[14.5px] text-neutral-900 placeholder:text-neutral-400 focus:outline-hidden leading-relaxed"
        />

        <div className="absolute bottom-3 right-3 flex items-center justify-end">
          <button
            type="submit"
            disabled={isLoading || disabled || !question.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-neutral-900 px-4 py-2 text-xs font-medium text-white shadow-xs hover:bg-neutral-800 disabled:bg-neutral-200 disabled:text-neutral-400 disabled:cursor-not-allowed transition-all duration-150 cursor-pointer"
          >
            {isLoading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Searching sources...</span>
              </>
            ) : (
              <>
                <Search className="w-3.5 h-3.5" />
                <span>Search</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
