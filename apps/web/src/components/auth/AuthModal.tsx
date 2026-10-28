import React, { useState } from "react";
import { X, Lock, Mail, Loader2, AlertCircle, CheckCircle2, UserPlus } from "lucide-react";
import { getSupabase } from "@/lib/supabaseClient";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function AuthModal({ isOpen, onClose, onSuccess }: AuthModalProps) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [infoMsg, setInfoMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);
    setInfoMsg(null);

    const sb = getSupabase();
    if (!sb) {
      setErrorMsg("Supabase client is not configured. Check NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local.");
      return;
    }

    if (mode === "signup" && password !== confirmPassword) {
      setErrorMsg("Passwords do not match.");
      return;
    }

    if (password.length < 8) {
      setErrorMsg("Password must be at least 8 characters long.");
      return;
    }

    setIsSubmitting(true);

    try {
      if (mode === "signin") {
        const { data, error } = await sb.auth.signInWithPassword({
          email: email.trim(),
          password: password,
        });

        if (error) {
          setErrorMsg(error.message);
          setIsSubmitting(false);
          return;
        }

        if (data.session) {
          setIsSubmitting(false);
          onSuccess();
          onClose();
        }
      } else {
        // Sign Up
        const { data, error } = await sb.auth.signUp({
          email: email.trim(),
          password: password,
        });

        if (error) {
          setErrorMsg(error.message);
          setIsSubmitting(false);
          return;
        }

        if (data.session) {
          // Auto-login after sign up (email confirmation disabled in Supabase)
          setIsSubmitting(false);
          onSuccess();
          onClose();
        } else if (data.user) {
          // Email confirmation required
          setIsSubmitting(false);
          setInfoMsg(
            "Account created! Please check your email to verify your address, then sign in. If your administrator has not yet added you to an organization, ask them to provision your membership."
          );
        }
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "Authentication request failed");
      setIsSubmitting(false);
    }
  };

  const toggleMode = (newMode: "signin" | "signup") => {
    setMode(newMode);
    setErrorMsg(null);
    setInfoMsg(null);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-neutral-900/40 backdrop-blur-xs animate-in fade-in duration-150">
      <div className="w-full max-w-sm max-h-[92vh] overflow-y-auto rounded-xl border border-neutral-200 bg-white p-5 sm:p-6 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-neutral-100 pb-3">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-neutral-900 text-white flex items-center justify-center">
              {mode === "signin" ? <Lock className="w-3.5 h-3.5" /> : <UserPlus className="w-3.5 h-3.5" />}
            </div>
            <h3 className="text-sm font-semibold text-neutral-900">
              {mode === "signin" ? "Workspace Sign In" : "Create Account"}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-neutral-400 hover:text-neutral-700 rounded-md"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Tab switch between Sign In and Sign Up */}
        <div className="flex rounded-lg bg-neutral-100 p-0.5 text-xs font-medium">
          <button
            type="button"
            onClick={() => toggleMode("signin")}
            className={`flex-1 py-1.5 rounded-md text-center transition-all ${
              mode === "signin"
                ? "bg-white text-neutral-900 shadow-xs font-semibold"
                : "text-neutral-600 hover:text-neutral-900"
            }`}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => toggleMode("signup")}
            className={`flex-1 py-1.5 rounded-md text-center transition-all ${
              mode === "signup"
                ? "bg-white text-neutral-900 shadow-xs font-semibold"
                : "text-neutral-600 hover:text-neutral-900"
            }`}
          >
            Sign Up
          </button>
        </div>

        <p className="text-xs text-neutral-600 leading-relaxed">
          {mode === "signin"
            ? "Sign in with your organization Supabase credentials to access verified institutional memory."
            : "Register a new Supabase account. Once created, an organization administrator must grant membership to access private memory."}
        </p>

        {errorMsg && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-800 flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-rose-500 mt-0.5 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {infoMsg && (
          <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-xs text-emerald-800 flex items-start gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600 mt-0.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-medium">Verification Needed</p>
              <p className="text-[11px] leading-relaxed text-emerald-700">{infoMsg}</p>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-neutral-700 mb-1">
              Email
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 text-neutral-400 absolute left-3 top-2.5" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="eng@example.com"
                className="w-full pl-9 pr-3 py-2 text-xs rounded-lg border border-neutral-300 focus:outline-hidden focus:border-neutral-500 focus:ring-1 focus:ring-neutral-400"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-neutral-700 mb-1">
              Password
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-neutral-400 absolute left-3 top-2.5" />
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-9 pr-3 py-2 text-xs rounded-lg border border-neutral-300 focus:outline-hidden focus:border-neutral-500 focus:ring-1 focus:ring-neutral-400"
              />
            </div>
          </div>

          {mode === "signup" && (
            <div>
              <label className="block text-xs font-medium text-neutral-700 mb-1">
                Confirm Password
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-neutral-400 absolute left-3 top-2.5" />
                <input
                  type="password"
                  required
                  minLength={8}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full pl-9 pr-3 py-2 text-xs rounded-lg border border-neutral-300 focus:outline-hidden focus:border-neutral-500 focus:ring-1 focus:ring-neutral-400"
                />
              </div>
            </div>
          )}

          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full py-2 px-3 rounded-lg bg-neutral-900 text-white text-xs font-medium hover:bg-neutral-800 disabled:bg-neutral-300 flex items-center justify-center gap-1.5 transition-colors shadow-xs"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{mode === "signin" ? "Signing in..." : "Creating account..."}</span>
              </>
            ) : (
              <span>{mode === "signin" ? "Sign In" : "Create Account"}</span>
            )}
          </button>
        </form>

        <p className="text-[11px] text-neutral-400 text-center pt-1">
          Sessions are cryptographically verified by FastAPI before database queries execute.
        </p>
      </div>
    </div>
  );
}
