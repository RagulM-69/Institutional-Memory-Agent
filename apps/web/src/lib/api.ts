import {
  ActiveOrganization,
  AnswerFeedbackPayload,
  AnswerFeedbackResponse,
  ApiErrorDetail,
  AskRequestPayload,
  AskResponse,
  AuthenticatedUser,
  CreateHandoffPayload,
  CreateInvitationRequest,
  CreateKnowledgeNotePayload,
  CreateOrganizationRequest,
  CreateSourceRequest,
  DetectedSubjects,
  GenerateHandoffPayload,
  Handoff,
  HandoffItem,
  IngestMeetingPayload,
  IngestMeetingResponse,
  InvitationCreatedResponse,
  InvitationLookupResponse,
  InvitationSummary,
  KnowledgeNote,
  KnowledgeSource,
  MeetingSummary,
  OrganizationSummary,
  PaginatedSourceRecords,
  PendingUserInvitation,
  SyncResponse,
  TeamMember,
  UpdateHandoffItemPayload,
  UpdateHandoffPayload,
  UpdateMemberRoleRequest,
  UpdateSourceRequest,
  ValidateConfigRequest,
  ValidationResponse,
  OAuthStatusResponse,
  OAuthAuthorizeResponse,
  OAuthSessionResponse,
  FinalizeOAuthSessionRequest,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  recoveryHint?: string;

  constructor(message: string, status: number, recoveryHint?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.recoveryHint = recoveryHint;
  }
}

function parseErrorResponse(status: number, detail: unknown): ApiErrorDetail {
  let message = "An unexpected error occurred during request.";
  let hint: string | undefined;

  if (typeof detail === "string") {
    message = detail;
  } else if (typeof detail === "object" && detail !== null && "detail" in detail) {
    const d = (detail as { detail: unknown }).detail;
    if (typeof d === "string") {
      message = d;
    } else if (Array.isArray(d)) {
      message = d.map((item: { msg?: string }) => item.msg || JSON.stringify(item)).join(", ");
    }
  }

  if (status === 401) {
    hint = "Your session may have expired or is invalid. Please sign in again.";
  } else if (status === 403) {
    hint = "Access denied: Your account is not authorized for this organization context or lacks permission.";
  } else if (status === 409) {
    hint = "A conflicting operation is already in progress. Please wait for it to finish.";
  } else if (status === 429) {
    hint = "Rate limit reached for search or reasoning requests. Please wait a moment before trying again.";
  } else if (status === 503) {
    if (message.includes("GROQ_API_KEY")) {
      hint = "The backend requires GROQ_API_KEY to execute reasoning models. Configure it in .env.";
    } else {
      hint = "The upstream reasoning provider is temporarily unavailable or rate-limited. Try again shortly.";
    }
  } else if (status >= 500) {
    hint = "The backend encountered an internal error. Check API server logs for details.";
  }

  return {
    message,
    status,
    isRecoverable: status !== 401 && status !== 403,
    recoveryHint: hint,
  };
}

export async function checkApiHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function getCurrentUser(jwt: string): Promise<AuthenticatedUser> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/me`, {
      headers: {
        Authorization: `Bearer ${jwt}`,
        Accept: "application/json",
      },
    });

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }

    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running and reachable from your browser."
    );
  }
}

export async function getCurrentOrg(
  jwt: string,
  orgId?: string
): Promise<ActiveOrganization> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) {
    headers["X-Organization-Id"] = orgId;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/organization/current`, {
      headers,
    });

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }

    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running and reachable from your browser."
    );
  }
}

export async function askQuestion(
  question: string,
  jwt: string,
  orgId?: string,
  persist: boolean = true
): Promise<AskResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) {
    headers["X-Organization-Id"] = orgId;
  }

  const payload: AskRequestPayload = {
    question: question.trim(),
    persist,
  };

  try {
    const res = await fetch(`${API_BASE_URL}/api/ask`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }

    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running and reachable from your browser."
    );
  }
}

// ---------------------------------------------------------------------------
// Knowledge Notes
// ---------------------------------------------------------------------------

export async function listKnowledgeNotes(
  jwt: string,
  orgId?: string
): Promise<KnowledgeNote[]> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/knowledge-notes`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function createKnowledgeNote(
  payload: CreateKnowledgeNotePayload,
  jwt: string,
  orgId?: string
): Promise<KnowledgeNote> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/knowledge-notes`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

// ---------------------------------------------------------------------------
// Meeting Ingestion
// ---------------------------------------------------------------------------

export async function listMeetings(
  jwt: string,
  orgId?: string
): Promise<MeetingSummary[]> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/meetings`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function ingestMeeting(
  payload: IngestMeetingPayload,
  jwt: string,
  orgId?: string
): Promise<IngestMeetingResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/meetings`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function deleteMeeting(
  recordId: string,
  jwt: string,
  orgId?: string
): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/meetings/${recordId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return { success: true };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

// ---------------------------------------------------------------------------
// Handoffs
// ---------------------------------------------------------------------------

export async function listHandoffs(
  jwt: string,
  orgId?: string
): Promise<Handoff[]> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/handoffs`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function getHandoff(
  handoffId: string,
  jwt: string,
  orgId?: string
): Promise<Handoff> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/handoffs/${handoffId}`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function createHandoff(
  payload: CreateHandoffPayload,
  jwt: string,
  orgId?: string
): Promise<Handoff> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/handoffs`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function updateHandoff(
  handoffId: string,
  payload: UpdateHandoffPayload,
  jwt: string,
  orgId?: string
): Promise<Handoff> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/handoffs/${handoffId}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

// ---------------------------------------------------------------------------
// Answer Feedback
// ---------------------------------------------------------------------------

export async function submitAnswerFeedback(
  answerId: string,
  payload: AnswerFeedbackPayload,
  jwt: string,
  orgId?: string
): Promise<AnswerFeedbackResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/answers/${answerId}/feedback`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

// ---------------------------------------------------------------------------
// Knowledge Sources
// ---------------------------------------------------------------------------

export async function deleteKnowledgeNote(
  noteId: string,
  jwt: string,
  orgId?: string
): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/knowledge-notes/${noteId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return { success: true };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function listSources(
  jwt: string,
  orgId?: string
): Promise<KnowledgeSource[]> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function createSource(
  payload: CreateSourceRequest,
  jwt: string,
  orgId?: string
): Promise<KnowledgeSource> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function updateSource(
  sourceId: string,
  payload: UpdateSourceRequest,
  jwt: string,
  orgId?: string
): Promise<KnowledgeSource> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/${sourceId}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function syncSource(
  sourceId: string,
  jwt: string,
  orgId?: string,
  background = true
): Promise<SyncResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(
      `${API_BASE_URL}/api/sources/${sourceId}/sync?background=${background}`,
      {
        method: "POST",
        headers,
      }
    );
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function deleteSource(
  sourceId: string,
  jwt: string,
  orgId?: string
): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/${sourceId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return { success: true };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function getSourceRecords(
  sourceId: string,
  jwt: string,
  orgId?: string,
  limit = 20,
  offset = 0
): Promise<PaginatedSourceRecords> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(
      `${API_BASE_URL}/api/sources/${sourceId}/records?limit=${limit}&offset=${offset}`,
      { headers }
    );
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function validateSourceConfig(
  payload: ValidateConfigRequest,
  jwt: string,
  orgId?: string
): Promise<ValidationResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/validate`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function getOAuthStatus(
  jwt: string,
  orgId?: string
): Promise<OAuthStatusResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/oauth/status`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function getOAuthAuthorizeUrl(
  provider: string,
  jwt: string,
  orgId?: string
): Promise<OAuthAuthorizeResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/oauth/${provider}/authorize`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function getOAuthSession(
  sessionId: string,
  jwt: string,
  orgId?: string
): Promise<OAuthSessionResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/oauth/session/${sessionId}`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function finalizeOAuthSession(
  sessionId: string,
  payload: FinalizeOAuthSessionRequest,
  jwt: string,
  orgId?: string
): Promise<KnowledgeSource> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/sources/oauth/session/${sessionId}/finalize`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

// ---------------------------------------------------------------------------
// Organizations & Team Members
// ---------------------------------------------------------------------------

export async function listMyOrganizations(jwt: string): Promise<OrganizationSummary[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/me/organizations`, {
      headers: {
        Authorization: `Bearer ${jwt}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function createOrganization(
  payload: CreateOrganizationRequest,
  jwt: string
): Promise<OrganizationSummary> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/organizations`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function listTeamMembers(
  jwt: string,
  orgId?: string
): Promise<TeamMember[]> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/team/members`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function updateMemberRole(
  userId: string,
  payload: UpdateMemberRoleRequest,
  jwt: string,
  orgId?: string
): Promise<{ success: boolean; role: string }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/team/members/${userId}`, {
      method: "PATCH",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function removeMember(
  userId: string,
  jwt: string,
  orgId?: string
): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/team/members/${userId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

// ---------------------------------------------------------------------------
// Invitations
// ---------------------------------------------------------------------------

export async function createInvitation(
  payload: CreateInvitationRequest,
  jwt: string,
  orgId?: string
): Promise<InvitationCreatedResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function listInvitations(
  jwt: string,
  orgId?: string
): Promise<InvitationSummary[]> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations`, { headers });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function deleteInvitation(
  invitationId: string,
  jwt: string,
  orgId?: string,
  permanent: boolean = true
): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/${invitationId}?permanent=${permanent}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return { success: true };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function revokeInvitation(
  invitationId: string,
  jwt: string,
  orgId?: string
): Promise<{ success: boolean }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/${invitationId}`, {
      method: "DELETE",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function resendInvitation(
  invitationId: string,
  jwt: string,
  orgId?: string
): Promise<InvitationCreatedResponse> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/${invitationId}/resend`, {
      method: "POST",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function listMyPendingInvitations(
  jwt: string
): Promise<PendingUserInvitation[]> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/pending-for-me`, {
      headers: {
        Authorization: `Bearer ${jwt}`,
        Accept: "application/json",
      },
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function lookupInvitation(
  payload: { token?: string; code?: string; code_or_token?: string },
  jwt: string
): Promise<InvitationLookupResponse> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/lookup`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function acceptInvitation(
  payload: { invitation_id?: string; token?: string; code?: string; code_or_token?: string },
  jwt: string
): Promise<{ success: boolean; org_id: string; org_name: string; role: string }> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/accept`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

export async function declineInvitation(
  payload: { invitation_id?: string; token?: string; code?: string; code_or_token?: string },
  jwt: string
): Promise<{ success: boolean }> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/invitations/decline`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}

// ---------------------------------------------------------------------------
// Handoff Action Items
// ---------------------------------------------------------------------------

export async function updateHandoffItem(
  handoffId: string,
  itemId: string,
  payload: UpdateHandoffItemPayload,
  jwt: string,
  orgId?: string
): Promise<HandoffItem> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(
      `${API_BASE_URL}/api/handoffs/${handoffId}/items/${itemId}`,
      {
        method: "PATCH",
        headers,
        body: JSON.stringify(payload),
      }
    );
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(`Unable to reach API server at ${API_BASE_URL}.`, 0);
  }
}


export async function getDetectedSubjects(
  jwt: string,
  orgId?: string
): Promise<DetectedSubjects> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/handoffs/detected-subjects`, {
      method: "GET",
      headers,
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}

export async function generateHandoff(
  payload: GenerateHandoffPayload,
  jwt: string,
  orgId?: string
): Promise<Handoff> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${jwt}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (orgId) headers["X-Organization-Id"] = orgId;

  try {
    const res = await fetch(`${API_BASE_URL}/api/handoffs/generate`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      const parsed = parseErrorResponse(res.status, errBody);
      throw new ApiError(parsed.message, parsed.status, parsed.recoveryHint);
    }
    return res.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(
      `Unable to reach API server at ${API_BASE_URL}.`,
      0,
      "Verify the FastAPI backend is running."
    );
  }
}
