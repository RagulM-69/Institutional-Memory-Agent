"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  LayoutGrid,
  Database,
  BookOpen,
  UserCheck,
  Users,
  Settings,
  ChevronLeft,
  ChevronRight,
  Shield,
  Layers,
  X,
  Lock,
  LogOut,
  Copy,
  Check,
  Building2,
  CheckCircle2,
} from "lucide-react";
import { ActiveOrganization, AuthenticatedUser } from "@/lib/types";
import { getSupabase } from "@/lib/supabaseClient";

interface AppSidebarProps {
  currentPath?: string;
  isOpen?: boolean;
  onClose?: () => void;
  apiOnline?: boolean | null;
  org?: ActiveOrganization | null;
  user?: AuthenticatedUser | null;
  onSignOut?: () => void;
}

// 4-leaf clover brand logo
function CloverBrandLogo({ className = "w-7 h-7" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
    >
      <circle cx="11" cy="11" r="6" fill="#10B981" />
      <circle cx="21" cy="11" r="6" fill="#059669" />
      <circle cx="11" cy="21" r="6" fill="#059669" />
      <circle cx="21" cy="21" r="6" fill="#34D399" />
      <circle cx="16" cy="16" r="3" fill="#047857" />
    </svg>
  );
}

export function AppSidebar({
  currentPath = "/",
  isOpen = false,
  onClose,
  org = null,
  user = null,
  onSignOut,
}: AppSidebarProps) {
  // Single sidebar: collapsed (w-16) or expanded (w-64)
  const [isExpanded, setIsExpanded] = useState<boolean>(false);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);

  // User Profile Modal / Popover State
  const [isUserMenuOpen, setIsUserMenuOpen] = useState<boolean>(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("im_sidebar_expanded");
      if (stored !== null) {
        setIsExpanded(stored === "true");
      }
    } catch {
      // fallback
    }
  }, []);

  // Close user menu on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false);
      }
    }
    if (isUserMenuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isUserMenuOpen]);

  const toggleExpand = () => {
    setIsExpanded((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("im_sidebar_expanded", String(next));
      } catch {
        // fallback
      }
      return next;
    });
  };

  const handleCopyText = async (text: string, key: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 2000);
    } catch {
      // fallback
    }
  };

  const handleDefaultSignOut = async () => {
    if (onSignOut) {
      onSignOut();
      setIsUserMenuOpen(false);
      return;
    }
    const sb = getSupabase();
    if (sb) {
      await sb.auth.signOut();
    }
    window.location.href = "/";
  };

  interface NavItem {
    name: string;
    href: string;
    icon: React.ComponentType<{ className?: string }>;
    isActive: boolean;
    enabled: boolean;
    badge?: string;
  }

  const navItems: NavItem[] = [
    {
      name: "Ask Knowledge",
      href: "/",
      icon: LayoutGrid,
      isActive: currentPath === "/",
      enabled: true,
    },
    {
      name: "Knowledge Sources",
      href: "/sources",
      icon: Database,
      isActive: currentPath === "/sources",
      enabled: true,
    },
    {
      name: "Notes & Hub",
      href: "/knowledge",
      icon: BookOpen,
      isActive: currentPath === "/knowledge",
      enabled: true,
    },
    {
      name: "Engineer Dossiers",
      href: "/handoffs",
      icon: UserCheck,
      isActive: currentPath === "/handoffs",
      enabled: true,
    },
    {
      name: "Members & Access",
      href: "/team",
      icon: Users,
      isActive: currentPath === "/team",
      enabled: true,
    },
    {
      name: "App Settings",
      href: "/settings",
      icon: Settings,
      isActive: currentPath === "/settings",
      enabled: true,
    },
  ];

  // Derived user display details
  const displayEmail = user?.email || "owner@institutional-memory.local";
  const displayName = displayEmail.split("@")[0].replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const initials = org?.name
    ? org.name.substring(0, 2).toUpperCase()
    : displayName.substring(0, 2).toUpperCase();

  const userRole = org?.role || user?.role || "admin";

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 z-40 bg-neutral-900/30 backdrop-blur-xs lg:hidden"
          onClick={onClose}
        />
      )}

      {/* SINGLE UNIFIED SIDEBAR: Locked, stationary, smoothly expands from w-16 to w-64 */}
      <aside
        className={`fixed top-0 bottom-0 left-0 z-40 h-screen bg-white border-r border-neutral-200/90 flex flex-col justify-between py-4 select-none transition-all duration-300 ease-in-out lg:sticky lg:top-0 lg:translate-x-0 lg:h-screen lg:self-start lg:shrink-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        } ${isExpanded ? "w-64 px-4" : "w-16 px-2"}`}
      >
        {/* ======================================================== */}
        {/* TOP SECTION: BRAND LOGO + ORG HEADER                     */}
        {/* ======================================================== */}
        <div className="flex flex-col gap-6 w-full">
          {/* Header Row */}
          <div className="flex items-center justify-between w-full">
            {isExpanded ? (
              <div className="flex items-center justify-between w-full min-w-0">
                <Link
                  href="/"
                  className="flex items-center gap-3 min-w-0 group"
                  onClick={onClose}
                >
                  <CloverBrandLogo className="w-8 h-8 shrink-0 group-hover:scale-105 transition-transform" />
                  <div className="min-w-0">
                    <h2 className="text-sm font-bold text-neutral-900 truncate tracking-tight leading-tight">
                      {org?.name || "Acme Engineering"}
                    </h2>
                    <p className="text-[11px] text-neutral-400 font-mono truncate leading-normal">
                      {org ? `org: ${org.slug}` : "org: acme-engineering"}
                    </p>
                  </div>
                </Link>

                <button
                  type="button"
                  onClick={toggleExpand}
                  className="p-1.5 rounded-lg text-neutral-400 hover:text-neutral-700 hover:bg-neutral-100 transition-colors shrink-0 ml-1"
                  title="Collapse sidebar"
                  aria-label="Collapse sidebar"
                >
                  <ChevronLeft className="w-4 h-4 stroke-[2]" />
                </button>
              </div>
            ) : (
              <div className="w-full flex items-center justify-center">
                <button
                  type="button"
                  onClick={toggleExpand}
                  className="p-1 rounded-xl hover:bg-neutral-100 transition-all hover:scale-105 active:scale-95 focus:outline-hidden"
                  title="Expand sidebar"
                  aria-label="Expand sidebar"
                >
                  <CloverBrandLogo className="w-8 h-8 cursor-pointer" />
                </button>
              </div>
            )}
          </div>

          {/* ======================================================== */}
          {/* MIDDLE: SINGLE NAVIGATION LIST                           */}
          {/* ======================================================== */}
          <nav className="flex flex-col gap-1 w-full">
            {isExpanded && (
              <span className="px-2 text-[10px] font-semibold uppercase tracking-wider text-neutral-400 block mb-1">
                Workspace
              </span>
            )}

            {navItems.map((item) => {
              const Icon = item.icon;
              const isHovered = hoveredItem === item.name;

              if (!item.enabled) {
                return (
                  <div
                    key={item.name}
                    onMouseEnter={() => setHoveredItem(item.name)}
                    onMouseLeave={() => setHoveredItem(null)}
                    className={`relative rounded-xl text-neutral-300 cursor-not-allowed flex items-center ${
                      isExpanded ? "px-3 py-2.5 gap-3" : "p-2.5 justify-center"
                    }`}
                  >
                    <Icon className="w-5 h-5 shrink-0" />
                    {isExpanded && (
                      <div className="flex items-center justify-between flex-1 min-w-0">
                        <span className="text-xs font-medium text-neutral-400 truncate">{item.name}</span>
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-neutral-100 text-neutral-400 font-mono">
                          {item.badge}
                        </span>
                      </div>
                    )}

                    {!isExpanded && isHovered && (
                      <div className="absolute left-full ml-3 px-3 py-1.5 bg-neutral-900 text-white text-xs font-medium rounded-lg shadow-xl whitespace-nowrap z-50 pointer-events-none flex items-center gap-1.5 animate-in fade-in zoom-in-95 duration-150">
                        <span>{item.name}</span>
                        <span className="text-[9px] px-1 py-0.2 bg-neutral-800 rounded text-neutral-400 font-mono">
                          {item.badge}
                        </span>
                        <span className="absolute -left-1 top-1/2 -translate-y-1/2 border-y-4 border-y-transparent border-r-4 border-r-neutral-900" />
                      </div>
                    )}
                  </div>
                );
              }

              return (
                <div
                  key={item.name}
                  className="relative w-full"
                  onMouseEnter={() => setHoveredItem(item.name)}
                  onMouseLeave={() => setHoveredItem(null)}
                >
                  <Link
                    href={item.href}
                    onClick={onClose}
                    className={`rounded-xl transition-all flex items-center relative ${
                      isExpanded ? "px-3 py-2.5 gap-3" : "p-2.5 justify-center"
                    } ${
                      item.isActive
                        ? "bg-neutral-100 text-neutral-900 shadow-2xs font-semibold"
                        : "text-neutral-600 hover:text-neutral-900 hover:bg-neutral-50"
                    }`}
                  >
                    <Icon
                      className={`w-5 h-5 shrink-0 ${
                        item.isActive ? "text-neutral-900 stroke-[2.2]" : "text-neutral-500 stroke-[1.8]"
                      }`}
                    />

                    {isExpanded && (
                      <div className="flex items-center justify-between flex-1 min-w-0">
                        <span className="text-xs truncate">{item.name}</span>
                        {item.isActive && (
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                        )}
                      </div>
                    )}

                    {!isExpanded && item.isActive && (
                      <span className="absolute -left-1 top-1/2 -translate-y-1/2 w-1 h-4 bg-emerald-500 rounded-r-full" />
                    )}
                  </Link>

                  {/* Tooltip when collapsed */}
                  {!isExpanded && isHovered && (
                    <div className="absolute left-full ml-3 px-3 py-1.5 bg-neutral-900 text-white text-xs font-medium rounded-lg shadow-xl whitespace-nowrap z-50 pointer-events-none flex items-center gap-1.5 animate-in fade-in zoom-in-95 duration-150">
                      <span>{item.name}</span>
                      <span className="absolute -left-1 top-1/2 -translate-y-1/2 border-y-4 border-y-transparent border-r-4 border-r-neutral-900" />
                    </div>
                  )}
                </div>
              );
            })}
          </nav>
        </div>

        {/* ======================================================== */}
        {/* BOTTOM SECTION: EXPAND TOGGLE + USER AVATAR & FLYOUT     */}
        {/* ======================================================== */}
        <div className="flex flex-col gap-2 w-full pt-2 border-t border-neutral-100 relative">
          {/* Expand / Collapse Button */}
          <button
            type="button"
            onClick={toggleExpand}
            className={`rounded-xl text-neutral-400 hover:text-neutral-800 hover:bg-neutral-50 transition-colors flex items-center ${
              isExpanded ? "px-3 py-2 gap-2 text-xs font-medium" : "p-2.5 justify-center w-full"
            }`}
            title={isExpanded ? "Collapse Sidebar" : "Expand Sidebar"}
          >
            {isExpanded ? (
              <>
                <ChevronLeft className="w-4 h-4 stroke-[2]" />
                <span className="text-neutral-500">Collapse</span>
              </>
            ) : (
              <ChevronRight className="w-4 h-4 stroke-[2]" />
            )}
          </button>

          {/* USER PROFILE BUTTON (AVATAR CIRCLE) */}
          <div className="relative w-full">
            <button
              type="button"
              onClick={() => setIsUserMenuOpen(!isUserMenuOpen)}
              className={`rounded-xl transition-all flex items-center focus:outline-hidden w-full ${
                isExpanded
                  ? "p-2 gap-3 hover:bg-neutral-50 border border-transparent hover:border-neutral-200/60"
                  : "p-1 justify-center hover:scale-105"
              }`}
              title="View User & Organization Profile"
              aria-label="User Profile"
            >
              <div className="w-9 h-9 rounded-full bg-amber-200 border-2 border-amber-300 hover:border-amber-400 flex items-center justify-center text-amber-950 font-bold text-xs shadow-xs shrink-0 select-none">
                {initials}
              </div>

              {isExpanded && (
                <div className="flex items-center justify-between flex-1 min-w-0 text-left">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-neutral-900 truncate">
                      {displayName}
                    </p>
                    <p className="text-[10px] text-neutral-400 font-mono truncate">
                      {userRole}
                    </p>
                  </div>
                  <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" title="Active Session" />
                </div>
              )}
            </button>

            {/* FLOATING USER PROFILE FLYOUT POPOVER CARD */}
            {isUserMenuOpen && (
              <div
                ref={userMenuRef}
                className="absolute left-full bottom-0 ml-3 w-80 rounded-2xl bg-white border border-neutral-200/90 shadow-2xl p-5 z-50 space-y-4 animate-in fade-in zoom-in-95 duration-150 text-neutral-900 select-text"
              >
                {/* Popover Header */}
                <div className="flex items-start justify-between gap-3 pb-3 border-b border-neutral-100">
                  <div className="flex items-center gap-3">
                    <div className="w-11 h-11 rounded-full bg-amber-200 border-2 border-amber-300 flex items-center justify-center text-amber-950 font-bold text-sm shadow-xs shrink-0 relative select-none">
                      {initials}
                      <span className="absolute bottom-0 right-0 w-3 h-3 rounded-full bg-emerald-500 ring-2 ring-white" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-sm font-bold text-neutral-900 truncate">
                        {displayName}
                      </h3>
                      <p className="text-xs text-neutral-500 truncate font-mono">
                        {displayEmail}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsUserMenuOpen(false)}
                    className="p-1 rounded-md text-neutral-400 hover:text-neutral-700 hover:bg-neutral-100 transition-colors"
                    title="Close"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>

                {/* Organization & Role Info */}
                <div className="rounded-xl bg-neutral-50/80 border border-neutral-200/80 p-3 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5 text-neutral-600 font-medium">
                      <Building2 className="w-3.5 h-3.5 text-neutral-400" />
                      <span>Organization:</span>
                    </div>
                    <span className="font-semibold text-neutral-900 truncate max-w-[140px]">
                      {org?.name || "Acme Engineering"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5 text-neutral-600 font-medium">
                      <Shield className="w-3.5 h-3.5 text-neutral-400" />
                      <span>Assigned Role:</span>
                    </div>
                    <span
                      className={`capitalize px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                        userRole === "admin"
                          ? "bg-purple-50 text-purple-700 border-purple-200"
                          : userRole === "team_lead"
                          ? "bg-blue-50 text-blue-700 border-blue-200"
                          : "bg-emerald-50 text-emerald-700 border-emerald-200"
                      }`}
                    >
                      {userRole.replace("_", " ")}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1.5 text-neutral-600 font-medium">
                      <Lock className="w-3.5 h-3.5 text-neutral-400" />
                      <span>Data Isolation:</span>
                    </div>
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700">
                      <CheckCircle2 className="w-3 h-3 text-emerald-600" />
                      <span>RLS Enforced</span>
                    </span>
                  </div>
                </div>

                {/* Identifier Essentials */}
                <div className="space-y-1.5 text-xs text-neutral-500 font-mono">
                  <div className="flex items-center justify-between py-0.5">
                    <span className="text-[11px] text-neutral-400">Org ID:</span>
                    <div className="flex items-center gap-1">
                      <span className="text-[11px] text-neutral-700">
                        {org?.org_id ? `${org.org_id.substring(0, 8)}...` : "89c99fb8..."}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleCopyText(org?.org_id || "89c99fb8-0a30-45e8-9132-bbc5c985c4f2", "org_id")}
                        className="p-1 hover:text-neutral-900 rounded"
                        title="Copy Org ID"
                      >
                        {copiedKey === "org_id" ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                      </button>
                    </div>
                  </div>

                  {user?.id && (
                    <div className="flex items-center justify-between py-0.5">
                      <span className="text-[11px] text-neutral-400">User ID:</span>
                      <div className="flex items-center gap-1">
                        <span className="text-[11px] text-neutral-700">
                          {`${user.id.substring(0, 8)}...`}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleCopyText(user.id, "user_id")}
                          className="p-1 hover:text-neutral-900 rounded"
                          title="Copy User ID"
                        >
                          {copiedKey === "user_id" ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* Actions / Sign Out */}
                <div className="pt-2 border-t border-neutral-100 flex items-center justify-between gap-2">
                  <Link
                    href="/team"
                    onClick={() => setIsUserMenuOpen(false)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-neutral-200 hover:bg-neutral-50 text-xs font-medium text-neutral-700 transition-colors shadow-2xs"
                  >
                    <Users className="w-3.5 h-3.5 text-neutral-500" />
                    <span>Manage Team</span>
                  </Link>

                  <button
                    type="button"
                    onClick={handleDefaultSignOut}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 text-xs font-medium transition-colors shadow-2xs"
                  >
                    <LogOut className="w-3.5 h-3.5 text-rose-600" />
                    <span>Sign Out</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
