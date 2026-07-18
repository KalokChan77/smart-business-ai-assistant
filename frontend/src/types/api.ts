export type RoleCode = "admin" | "decision_maker" | "customer_service" | "user";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface CurrentUser {
  id: string;
  tenant_id: string;
  username: string;
  email: string;
  roles: RoleCode[];
}

export interface PlatformErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
  request_id?: string;
  detail?: unknown;
}

export interface PageResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Conversation {
  id: string;
  title: string;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface ConversationMessage {
  id: string;
  position: number;
  role: MessageRole;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface KnowledgeCitation {
  rank: number;
  document_name: string;
  excerpt: string;
  score?: number | null;
}

export interface KnowledgeAnswer {
  outcome: "answered" | "no_match" | "refused";
  answer: string;
  citations: KnowledgeCitation[];
  retrieval_count: number;
}

export type TicketStatus = "open" | "in_progress" | "resolved" | "closed";
export type TicketPriority = "low" | "normal" | "high" | "urgent";
export type TicketCategory =
  | "refund_after_sales"
  | "account_security"
  | "product_service"
  | "knowledge_document"
  | "technical_support"
  | "other";

export interface ConfirmedReply {
  final_reply: string;
  confirmed_at: string;
}

export interface CustomerTicket {
  id: string;
  subject: string;
  description: string;
  status: TicketStatus;
  category: TicketCategory | null;
  priority: TicketPriority;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
  requester_user_id?: string;
  assigned_user_id?: string | null;
  classification_confidence?: number | null;
  classification_reason?: string | null;
}

export type CustomerTicketDetail =
  | {
      view: "public";
      ticket: CustomerTicket;
      confirmed_reply: ConfirmedReply | null;
    }
  | {
      view: "internal";
      ticket: CustomerTicket;
      reply_suggestion: ReplySuggestion | null;
    };

export interface TicketClassification {
  ticket_id: string;
  category: TicketCategory;
  priority: TicketPriority;
  confidence: number;
  reason: string;
}

export interface CustomerServiceCitation {
  document_name: string;
  excerpt: string;
  rank?: number;
}

export interface ReplySuggestion {
  id: string;
  ticket_id: string;
  status: "draft" | "confirmed";
  category: TicketCategory;
  suggested_reply: string;
  final_reply?: string | null;
  knowledge_outcome: "answered" | "no_match" | "refused";
  quality_status: "passed" | "needs_review";
  citations: CustomerServiceCitation[];
  quality_notes: string[];
  workflow_version: string;
  generated_by_user_id: string | null;
  confirmed_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at?: string | null;
}

export interface UserAccount {
  id: string;
  tenant_id: string;
  username: string;
  email: string;
  status: "active" | "disabled";
  roles: RoleCode[];
  created_at: string;
  updated_at: string;
}

export type KnowledgeDocumentStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "deleted";

export interface KnowledgeDocument {
  id: string;
  filename: string;
  media_type: string;
  extension: string;
  size_bytes: number;
  status: KnowledgeDocumentStatus;
  indexing_status: string | null;
  latest_error_code: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeJob {
  id: string;
  document_id: string;
  operation: "upload" | "reindex" | "delete";
  status: "pending" | "processing" | "completed" | "failed";
  indexing_status: string | null;
  completed_segments: number | null;
  total_segments: number | null;
  error_code: string | null;
  started_at: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocumentOperation {
  document: KnowledgeDocument;
  job: KnowledgeJob;
}

export interface AnalyticsPeriod {
  start_date: string;
  end_date: string;
  timezone: "UTC";
}

export interface AnalyticsOverview {
  period: AnalyticsPeriod;
  consultation_count: number;
  resolved_consultation_count: number;
  resolution_rate: number;
  human_takeover_count: number;
  human_takeover_rate: number;
  ai_run_count: number;
  ai_terminal_run_count: number;
  ai_success_rate: number;
  feedback_count: number;
  positive_feedback_count: number;
  satisfaction_rate: number;
  top_questions: Array<{ question: string; count: number }>;
  summary_cards: Array<{
    code: string;
    title: string;
    value: string;
    description: string;
  }>;
}

export interface ConsultationTrend {
  period: AnalyticsPeriod;
  points: Array<{
    date: string;
    consultation_count: number;
    resolved_count: number;
    human_takeover_count: number;
  }>;
}

export interface CategoryDistribution {
  period: AnalyticsPeriod;
  total: number;
  items: Array<{
    category: TicketCategory | "unclassified";
    count: number;
    percentage: number;
  }>;
}

export interface SatisfactionMetrics {
  period: AnalyticsPeriod;
  feedback_count: number;
  positive_count: number;
  negative_count: number;
  satisfaction_rate: number;
}

export interface AIRunMetrics {
  period: AnalyticsPeriod;
  total: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  terminal: number;
  success_rate: number;
  average_duration_ms: number;
  average_input_tokens: number;
  average_output_tokens: number;
  by_model: Array<{
    provider: string;
    model: string;
    total: number;
    succeeded: number;
    failed: number;
    cancelled: number;
    running: number;
    terminal: number;
    success_rate: number;
    average_duration_ms: number;
  }>;
  errors: Array<{ code: string; count: number }>;
}

export type SseEventName =
  | "metadata"
  | "token"
  | "tool_start"
  | "tool_end"
  | "message_end"
  | "error";

export interface SseEvent<T = Record<string, unknown>> {
  event: SseEventName;
  data: T;
}
