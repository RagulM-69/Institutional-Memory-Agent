/**
 * Strict TypeScript types for Institutional Memory Agent v1 frontend.
 * Derived directly from the backend FastAPI contracts and database schemas.
 */

export type EvidenceLevel = "documented" | "inferred" | "unknown";
export type ClaimVerificationStatus = "verified" | "unsupported" | "dropped";
export type ClaimEvidenceType = "documented" | "inferred" | "unknown";

export interface VerifiedClaim {
  claim_text: string;
  record_id: string;
  record_version_id: string;
  chunk_id: string;
  exact_quote: string;
  quote_offset?: number | null;
  verification_status: ClaimVerificationStatus;
  evidence_type: ClaimEvidenceType;
  record_title: string;
  record_url?: string | null;
  record_type?: string | null;
}

export interface InvestigationTraceStep {
  step: number;
  action: string;
  query?: string;
  results_count?: number;
  duration_ms?: number;
  model?: string;
  candidate_claims_count?: number;
  verified_claims_count?: number;
  unsupported_claims_count?: number;
  evidence_level?: string;
  is_abstention?: boolean;
  staleness_warning?: string;
  error?: string;
  [key: string]: unknown;
}

export interface AskMetrics {
  tool_calls?: number;
  retrieved_chunks_count?: number;
  verified_claims_count?: number;
  unsupported_claims_count?: number;
  duration_seconds?: number;
  [key: string]: unknown;
}

export interface AskResponse {
  answer_id?: string | null;
  question: string;
  answer: string;
  evidence_level: EvidenceLevel;
  evidence_reason: string;
  is_abstention: boolean;
  staleness_warning?: string | null;
  claims: VerifiedClaim[];
  investigation_trace: InvestigationTraceStep[];
  metrics: AskMetrics;
}

export interface AskRequestPayload {
  question: string;
  persist?: boolean;
}

export interface AuthenticatedUser {
  id: string;
  email: string | null;
  role: string;
}

export interface ActiveOrganization {
  user_id: string;
  org_id: string;
  name: string;
  slug: string;
  role: "admin" | "team_lead" | "member" | string;
}

export interface ApiErrorDetail {
  message: string;
  status: number;
  isRecoverable: boolean;
  recoveryHint?: string;
}

// ---------------------------------------------------------------------------
// Knowledge Notes
// ---------------------------------------------------------------------------

export interface LinkedRecordSummary {
  id: string;
  title: string;
  record_type: string;
  external_id: string;
}

export interface KnowledgeNote {
  id: string;
  org_id: string;
  author_user_id?: string | null;
  title: string;
  content: string;
  status: string;
  is_human_contributed: boolean;
  created_at: string;
  updated_at: string;
  linked_records: LinkedRecordSummary[];
}

export interface CreateKnowledgeNotePayload {
  title: string;
  content: string;
  record_ids?: string[];
}

// ---------------------------------------------------------------------------
// Meeting Ingestion
// ---------------------------------------------------------------------------

export interface MeetingSummary {
  id: string;
  title: string;
  record_type: string;
  meeting_date?: string | null;
  contributed_by_user_id?: string | null;
  created_at: string;
  chunk_count: number;
}

export interface IngestMeetingPayload {
  title: string;
  content: string;
  meeting_date?: string | null;
  metadata?: Record<string, unknown>;
}

export interface IngestMeetingResponse {
  record_id: string;
  source_id: string;
  title: string;
  chunk_count: number;
  meeting_date: string;
  created_at: string;
  is_untrusted_evidence: boolean;
  status: string;
}

// ---------------------------------------------------------------------------
// Handoff Containers
// ---------------------------------------------------------------------------

export type HandoffSubjectType = "person" | "service";
export type HandoffStatus = "draft" | "reviewed" | "confirmed" | "acknowledged" | "archived";
export type HandoffItemStatus = "verified" | "inferred" | "unresolved" | "outdated";

export interface HandoffItem {
  id: string;
  title: string;
  description?: string | null;
  item_status: HandoffItemStatus;
  record_id?: string | null;
  record_title?: string | null;
  record_type?: string | null;
  note_id?: string | null;
  note_title?: string | null;
  gap_id?: string | null;
  assignee_user_id?: string | null;
  due_date?: string | null;
  is_restricted_evidence?: boolean;
}

export interface Handoff {
  id: string;
  org_id: string;
  title: string;
  subject_type: HandoffSubjectType;
  subject_identifier: string;
  status: HandoffStatus;
  summary?: string | null;
  created_by_user_id?: string | null;
  departing_user_id?: string | null;
  recipient_user_id?: string | null;
  created_at: string;
  item_count: number;
  items?: HandoffItem[];
}

export interface CreateHandoffItemPayload {
  title: string;
  description?: string;
  item_status: HandoffItemStatus;
  record_id?: string;
  note_id?: string;
  gap_id?: string;
  assignee_user_id?: string | null;
  due_date?: string | null;
}

export interface UpdateHandoffItemPayload {
  title?: string;
  description?: string;
  item_status?: HandoffItemStatus;
  assignee_user_id?: string | null;
  due_date?: string | null;
}

export interface CreateHandoffPayload {
  title: string;
  subject_type: HandoffSubjectType;
  subject_identifier: string;
  summary?: string;
  items?: CreateHandoffItemPayload[];
}

export interface UpdateHandoffPayload {
  title?: string;
  summary?: string;
  status?: HandoffStatus;
}

export interface DetectedSubjects {
  engineers: string[];
  services: string[];
}

export interface GenerateHandoffPayload {
  subject_type: HandoffSubjectType;
  subject_identifier: string;
  recipient_user_id?: string;
}

// ---------------------------------------------------------------------------
// Answer Feedback
// ---------------------------------------------------------------------------

export interface AnswerFeedbackPayload {
  rating: number; // 1 or -1
  notes?: string;
}

export interface AnswerFeedbackResponse {
  answer_id: string;
  feedback_rating: number;
  feedback_notes?: string | null;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Knowledge Sources
// ---------------------------------------------------------------------------

export type SourceType = "github" | "jira" | "slack" | "meeting";
export type SyncStatus = "ok" | "running" | "failed" | "partial";
export type SourceVisibility = "public" | "restricted";

export interface KnowledgeSource {
  id: string;
  org_id: string;
  name: string;
  type: SourceType;
  visibility: SourceVisibility;
  config: Record<string, unknown>;
  sync_status: SyncStatus;
  sync_cursor?: Record<string, unknown>;
  last_synced_at?: string | null;
  error_message?: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  record_count: number;
  has_encrypted_credentials?: boolean;
}

export interface CreateSourceRequest {
  name: string;
  type: SourceType;
  visibility: SourceVisibility;
  config: Record<string, unknown>;
  credentials?: Record<string, string>;
}

export interface UpdateSourceRequest {
  name?: string;
  visibility?: SourceVisibility;
  config?: Record<string, unknown>;
  is_archived?: boolean;
}

export interface SourceRecord {
  id: string;
  org_id: string;
  source_id: string;
  external_id: string;
  record_type: string;
  created_at: string;
  updated_at: string;
  current_version_id?: string | null;
  version_index?: number | null;
  title?: string | null;
  author_name?: string | null;
  url?: string | null;
  snippet?: string | null;
  chunk_count: number;
}

export interface PaginatedSourceRecords {
  items: SourceRecord[];
  total: number;
  limit: number;
  offset: number;
}

export interface SyncResponse {
  source_id: string;
  status: string;
  message: string;
  records_scanned?: number;
  records_created?: number;
  records_updated?: number;
  chunks_created?: number;
  errors?: string[];
  duration_seconds?: number;
}

export interface ValidateConfigRequest {
  type: string;
  config: Record<string, unknown>;
  credentials?: Record<string, string>;
}

export interface ValidationResponse {
  is_valid: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface OAuthProviderStatus {
  provider: string;
  available: boolean;
  missing_env_vars: string[];
  redirect_uri: string;
  scopes: string[];
}

export interface OAuthStatusResponse {
  providers: Record<string, OAuthProviderStatus>;
}

export interface OAuthAuthorizeResponse {
  provider: string;
  authorize_url: string;
  state: string;
}

export interface OAuthSessionTarget {
  id: string;
  name: string;
  description?: string | null;
  extra?: Record<string, unknown>;
}

export interface OAuthSessionResponse {
  session_id: string;
  provider: string;
  account_name: string;
  targets: OAuthSessionTarget[];
}

export interface FinalizeOAuthSessionRequest {
  name: string;
  target_id: string;
  visibility: SourceVisibility;
}

// ---------------------------------------------------------------------------
// Team & Organization Management
// ---------------------------------------------------------------------------

export type MemberRole = "admin" | "team_lead" | "member";

export interface OrganizationSummary {
  org_id: string;
  name: string;
  slug: string;
  role: MemberRole;
  created_at: string;
}

export interface CreateOrganizationRequest {
  name: string;
  slug: string;
}

export interface TeamMember {
  id: string;
  user_id: string;
  email: string | null;
  role: MemberRole;
  created_at: string;
  is_self?: boolean;
}

export interface UpdateMemberRoleRequest {
  role: MemberRole;
}

export type InvitationStatus = "pending" | "accepted" | "expired" | "revoked";

export interface InvitationSummary {
  id: string;
  org_id: string;
  email: string;
  role: MemberRole;
  status: InvitationStatus;
  invited_by_user_id: string;
  invited_by_email?: string | null;
  created_at: string;
  expires_at: string;
  accepted_at?: string | null;
}

export interface InvitationCreatedResponse extends InvitationSummary {
  token: string;
  code: string;
  raw_token?: string;
  raw_code?: string;
  invitation_link: string;
}

export interface CreateInvitationRequest {
  email: string;
  role: MemberRole;
}

export interface PendingUserInvitation {
  id: string;
  org_id: string;
  org_name: string;
  org_slug: string;
  role: MemberRole;
  email: string;
  created_at: string;
  expires_at: string;
}

export interface InvitationLookupResponse {
  id: string;
  org_id?: string;
  org_name: string;
  org_slug: string;
  role: MemberRole;
  masked_email?: string;
  email: string;
  is_expired: boolean;
  can_accept: boolean;
  email_matches?: boolean;
}
