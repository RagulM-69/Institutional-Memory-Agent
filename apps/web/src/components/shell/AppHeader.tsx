import React from "react";
import Link from "next/link";
import {
  Menu,
  Building2,
  User,
  LogOut,
  LogIn,
} from "lucide-react";
import { ActiveOrganization, AuthenticatedUser } from "@/lib/types";

interface AppHeaderProps {
  user: AuthenticatedUser | null;
  org: ActiveOrganization | null;
  title?: string;
  apiOnline?: boolean | null;
  onOpenSidebar?: () => void;
  onToggleSidebar?: () => void;
  onSignOut?: () => void;
  onSignIn?: () => void;
  onOpenAuth?: () => void;
}

export function AppHeader({
  user,
  org,
  title = "Ask Knowledge",
  apiOnline = null,
  onOpenSidebar,
  onToggleSidebar,
  onSignOut,
  onSignIn,
  onOpenAuth,
}: AppHeaderProps) {
  const handleSidebar = onToggleSidebar || onOpenSidebar;
  const handleAuth = onOpenAuth || onSignIn;
  return (
    <header className="h-14 border-b border-neutral-200/90 bg-white/95 backdrop-blur-xs px-4 sm:px-6 flex items-center justify-between sticky top-0 z-30">
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSidebar}
          className="lg:hidden p-1.5 -ml-1 text-neutral-600 hover:text-neutral-900 rounded-md hover:bg-neutral-100"
          aria-label="Toggle navigation menu"
        >
          <Menu className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-2 text-xs">
          <span className="font-medium text-neutral-500 hidden sm:inline">
            Workspace
          </span>
          <span className="text-neutral-300 hidden sm:inline">/</span>
          <h1 className="font-semibold text-neutral-900 text-sm">
            {title}
          </h1>
          {apiOnline !== null && (
            <span
              className={`w-2 h-2 rounded-full ${apiOnline ? "bg-emerald-500" : "bg-amber-500"}`}
              title={apiOnline ? "API Operational" : "API Offline"}
            />
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Organization context badge */}
        {org ? (
          <Link
            href="/team"
            className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-neutral-100 hover:bg-neutral-200 text-neutral-800 text-xs border border-neutral-200 transition-colors"
            title="Manage Organization & Team"
          >
            <Building2 className="w-3.5 h-3.5 text-neutral-500" />
            <span className="font-medium">{org.name}</span>
            <span className="text-[10px] uppercase font-mono px-1 rounded bg-neutral-200 text-neutral-600">
              {org.role}
            </span>
          </Link>
        ) : user ? (
          <Link
            href="/team"
            className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-50 hover:bg-amber-100 text-amber-900 text-xs border border-amber-300 transition-colors font-medium"
            title="Create an organization or accept an invitation"
          >
            <Building2 className="w-3.5 h-3.5 text-amber-700" />
            <span>Create / Join Org</span>
          </Link>
        ) : (
          <div className="hidden sm:flex items-center gap-1 px-2.5 py-1 rounded-md bg-neutral-50 text-neutral-400 text-xs border border-neutral-200/70">
            <Building2 className="w-3.5 h-3.5 text-neutral-400" />
            <span>No active organization</span>
          </div>
        )}

        {/* User Account Controls */}
        {user ? (
          <div className="flex items-center gap-2">
            <div
              className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-neutral-700 bg-neutral-50 border border-neutral-200"
              title={`Signed in as ${user.email || user.id}`}
            >
              <User className="w-3.5 h-3.5 text-neutral-500" />
              <span className="max-w-[130px] truncate hidden md:inline">
                {user.email || "Authenticated User"}
              </span>
            </div>

            {onSignOut && (
              <button
                type="button"
                onClick={onSignOut}
                className="p-1.5 text-neutral-500 hover:text-neutral-800 rounded-md hover:bg-neutral-100 transition-colors"
                title="Sign out of workspace"
                aria-label="Sign out"
              >
                <LogOut className="w-4 h-4" />
              </button>
            )}
          </div>
        ) : (
          handleAuth && (
            <button
              type="button"
              onClick={handleAuth}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-neutral-900 text-white text-xs font-medium hover:bg-neutral-800 shadow-xs transition-colors"
            >
              <LogIn className="w-3.5 h-3.5" />
              <span>Sign In</span>
            </button>
          )
        )}
      </div>
    </header>
  );
}
