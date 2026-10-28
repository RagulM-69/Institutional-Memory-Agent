import React from "react";

interface LogoProps {
  className?: string;
  size?: number;
}

export function GitHubLogo({ className = "w-4 h-4", size }: LogoProps) {
  return (
    <svg
      role="img"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>GitHub</title>
      <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
    </svg>
  );
}

export function JiraLogo({ className = "w-4 h-4", size }: LogoProps) {
  return (
    <svg
      role="img"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>Jira</title>
      <defs>
        <linearGradient id="jiraGrad1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#0052CC" />
          <stop offset="100%" stopColor="#2684FF" />
        </linearGradient>
      </defs>
      <path
        d="M11.53 2c0 5.25 4.25 9.5 9.5 9.5h.97v-9.5H11.53z"
        fill="url(#jiraGrad1)"
      />
      <path
        d="M2 11.53c0 5.25 4.25 9.5 9.5 9.5h.97v-9.5H2z"
        fill="#0052CC"
      />
      <path
        d="M11.53 11.53c-5.25 0-9.53 4.28-9.53 9.53V22h9.53v-10.47z"
        fill="#2684FF"
        opacity="0.9"
      />
    </svg>
  );
}

export function SlackLogo({ className = "w-4 h-4", size }: LogoProps) {
  return (
    <svg
      role="img"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>Slack</title>
      {/* Top Left - Red/Magenta */}
      <path
        d="M5.042 15.165a2.528 2.528 0 0 1-2.52-2.523 2.52 2.52 0 0 1 2.52-2.52h2.52v5.043H5.042z"
        fill="#E01E5A"
      />
      <path
        d="M8.83 15.165a2.52 2.52 0 0 1 2.521-2.523 2.528 2.528 0 0 1 2.52 2.523v6.313A2.52 2.52 0 0 1 11.35 24a2.528 2.528 0 0 1-2.52-2.522v-6.313z"
        fill="#E01E5A"
      />
      {/* Top Right - Cyan */}
      <path
        d="M8.83 5.042a2.528 2.528 0 0 1 2.52-2.52 2.52 2.52 0 0 1 2.521 2.52v2.52H8.83V5.042z"
        fill="#36C5F0"
      />
      <path
        d="M8.83 8.83a2.52 2.52 0 0 1 2.52-2.521 2.528 2.528 0 0 1 2.521 2.52v6.313A2.52 2.52 0 0 1 11.35 17.67a2.528 2.528 0 0 1-2.52-2.523V8.83z"
        fill="#36C5F0"
      />
      {/* Bottom Right - Green */}
      <path
        d="M18.958 8.83a2.528 2.528 0 0 1 2.522 2.521 2.52 2.52 0 0 1-2.522 2.52h-2.52V8.83h2.52z"
        fill="#2EB67D"
      />
      <path
        d="M15.17 8.83a2.52 2.52 0 0 1-2.52 2.52 2.528 2.528 0 0 1-2.523-2.52V2.52A2.52 2.52 0 0 1 12.65 0a2.528 2.528 0 0 1 2.52 2.522v6.308z"
        fill="#2EB67D"
      />
      {/* Bottom Left - Yellow */}
      <path
        d="M15.17 18.958a2.528 2.528 0 0 1-2.52 2.522 2.52 2.52 0 0 1-2.523-2.522v-2.52h5.043v2.52z"
        fill="#ECB22E"
      />
      <path
        d="M15.17 15.165a2.52 2.52 0 0 1-2.52 2.521 2.528 2.528 0 0 1-2.523-2.521V8.852A2.52 2.52 0 0 1 12.65 6.33a2.528 2.528 0 0 1 2.52 2.522v6.313z"
        fill="#ECB22E"
      />
    </svg>
  );
}

export function BrandLogo({
  type,
  className = "w-4 h-4",
  size,
}: {
  type: string;
  className?: string;
  size?: number;
}) {
  switch (type.toLowerCase()) {
    case "github":
      return <GitHubLogo className={className} size={size} />;
    case "jira":
      return <JiraLogo className={className} size={size} />;
    case "slack":
      return <SlackLogo className={className} size={size} />;
    default:
      return (
        <svg
          role="img"
          viewBox="0 0 24 24"
          width={size}
          height={size}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={className}
        >
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
        </svg>
      );
  }
}

