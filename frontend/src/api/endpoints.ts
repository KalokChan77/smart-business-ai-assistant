import { apiBlob, apiRequest } from "@/api/client";
import type {
  AIRunMetrics,
  AnalyticsOverview,
  CategoryDistribution,
  Conversation,
  ConversationMessage,
  CurrentUser,
  CustomerTicket,
  CustomerTicketDetail,
  KnowledgeAnswer,
  KnowledgeDocument,
  KnowledgeDocumentOperation,
  KnowledgeJob,
  PageResponse,
  ReplySuggestion,
  RoleCode,
  SatisfactionMetrics,
  TicketCategory,
  TicketClassification,
  TicketStatus,
  TokenPair,
  UserAccount,
  ConsultationTrend,
} from "@/types/api";

export interface HealthResponse {
  status: string;
}

function queryString(values: Record<string, string | number | undefined | null>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const authApi = {
  login(payload: { tenant_id: string; username: string; password: string }) {
    return apiRequest<TokenPair>(
      "/auth/login",
      { method: "POST", body: JSON.stringify(payload) },
      { auth: false, retryOnUnauthorized: false },
    );
  },
  me() {
    return apiRequest<CurrentUser>("/auth/me");
  },
  logout(refreshToken: string) {
    return apiRequest<void>("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
  },
};

export const healthApi = {
  live() {
    return apiRequest<HealthResponse>("/health", {}, { auth: false, retryOnUnauthorized: false });
  },
  ready() {
    return apiRequest<HealthResponse>(
      "/health/ready",
      {},
      { auth: false, retryOnUnauthorized: false },
    );
  },
};

export const conversationApi = {
  list(limit = 50, offset = 0) {
    return apiRequest<PageResponse<Conversation>>(
      `/conversations${queryString({ limit, offset })}`,
    );
  },
  create(title?: string) {
    return apiRequest<Conversation>("/conversations", {
      method: "POST",
      body: JSON.stringify({ title: title || null }),
    });
  },
  messages(conversationId: string, limit = 100, offset = 0) {
    return apiRequest<PageResponse<ConversationMessage>>(
      `/conversations/${conversationId}/messages${queryString({ limit, offset })}`,
    );
  },
  remove(conversationId: string) {
    return apiRequest<void>(`/conversations/${conversationId}`, { method: "DELETE" });
  },
};

export const aiApi = {
  feedback(runId: string, rating: "positive" | "negative", comment?: string) {
    return apiRequest(`/ai/runs/${runId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ rating, comment: comment || null }),
    });
  },
  tts(text: string) {
    return apiBlob("/audio/tts", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },
};

export const knowledgeApi = {
  query(query: string) {
    return apiRequest<KnowledgeAnswer>("/knowledge/query", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
  },
  listDocuments(limit = 50, offset = 0) {
    return apiRequest<PageResponse<KnowledgeDocument>>(
      `/knowledge/documents${queryString({ limit, offset })}`,
    );
  },
  upload(file: File) {
    const form = new FormData();
    form.append("file", file);
    return apiRequest<KnowledgeDocumentOperation>("/knowledge/documents", {
      method: "POST",
      body: form,
    });
  },
  job(jobId: string) {
    return apiRequest<KnowledgeJob>(`/knowledge/jobs/${jobId}`);
  },
  reindex(documentId: string) {
    return apiRequest<KnowledgeDocumentOperation>(
      `/knowledge/documents/${documentId}/reindex`,
      { method: "POST" },
    );
  },
  remove(documentId: string) {
    return apiRequest<KnowledgeDocumentOperation>(`/knowledge/documents/${documentId}`, {
      method: "DELETE",
    });
  },
};

export const ticketApi = {
  list(options: {
    status?: TicketStatus;
    category?: TicketCategory;
    limit?: number;
    offset?: number;
  } = {}) {
    return apiRequest<PageResponse<CustomerTicket>>(
      `/customer-service/tickets${queryString({
        status: options.status,
        category: options.category,
        limit: options.limit ?? 50,
        offset: options.offset ?? 0,
      })}`,
    );
  },
  create(subject: string, description: string) {
    return apiRequest<CustomerTicket>("/customer-service/tickets", {
      method: "POST",
      body: JSON.stringify({ subject, description }),
    });
  },
  get(ticketId: string) {
    return apiRequest<CustomerTicketDetail>(`/customer-service/tickets/${ticketId}`);
  },
  classify(ticketId: string) {
    return apiRequest<TicketClassification>("/customer-service/classify", {
      method: "POST",
      body: JSON.stringify({ ticket_id: ticketId }),
    });
  },
  suggest(ticketId: string) {
    return apiRequest<ReplySuggestion>("/customer-service/reply-suggestions", {
      method: "POST",
      body: JSON.stringify({ ticket_id: ticketId }),
    });
  },
  confirm(suggestionId: string, finalReply: string) {
    return apiRequest<CustomerTicketDetail>(
      `/customer-service/reply-suggestions/${suggestionId}/confirm`,
      { method: "POST", body: JSON.stringify({ final_reply: finalReply }) },
    );
  },
};

export const usersApi = {
  list() {
    return apiRequest<UserAccount[]>("/users");
  },
  create(payload: {
    username: string;
    email: string;
    password: string;
    role_codes: RoleCode[];
  }) {
    return apiRequest<UserAccount>("/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  update(
    userId: string,
    payload: { email?: string; status?: "active" | "disabled"; role_codes?: RoleCode[] },
  ) {
    return apiRequest<UserAccount>(`/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },
};

export const analyticsApi = {
  overview(startDate?: string, endDate?: string) {
    return apiRequest<AnalyticsOverview>(
      `/analytics/overview${queryString({ start_date: startDate, end_date: endDate })}`,
    );
  },
  consultations(startDate?: string, endDate?: string) {
    return apiRequest<ConsultationTrend>(
      `/analytics/consultations${queryString({
        start_date: startDate,
        end_date: endDate,
      })}`,
    );
  },
  categories(startDate?: string, endDate?: string) {
    return apiRequest<CategoryDistribution>(
      `/analytics/categories${queryString({ start_date: startDate, end_date: endDate })}`,
    );
  },
  satisfaction(startDate?: string, endDate?: string) {
    return apiRequest<SatisfactionMetrics>(
      `/analytics/satisfaction${queryString({ start_date: startDate, end_date: endDate })}`,
    );
  },
  aiRuns(startDate?: string, endDate?: string) {
    return apiRequest<AIRunMetrics>(
      `/analytics/ai-runs${queryString({ start_date: startDate, end_date: endDate })}`,
    );
  },
};
