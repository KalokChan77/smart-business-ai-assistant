import { clearTokenPair, readTokenPair, writeTokenPair } from "@/auth/session";
import type { PlatformErrorBody, TokenPair } from "@/types/api";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");
const AUTH_EXPIRED_EVENT = "smart-business-ai:auth-expired";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor(options: {
    status: number;
    code: string;
    message: string;
    requestId?: string | null;
    details?: unknown;
  }) {
    super(options.message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId ?? null;
    this.details = options.details;
  }
}

type RequestOptions = {
  auth?: boolean;
  retryOnUnauthorized?: boolean;
};

let refreshPromise: Promise<TokenPair | null> | null = null;

function notifyAuthExpired(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
  }
}

function headersFor(init: RequestInit, auth: boolean): Headers {
  const headers = new Headers(init.headers);
  const body = init.body;
  if (body && !(body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Accept", headers.get("Accept") || "application/json");
  if (auth) {
    const pair = readTokenPair();
    if (pair) {
      headers.set("Authorization", `Bearer ${pair.access_token}`);
    }
  }
  return headers;
}

async function refreshTokens(): Promise<TokenPair | null> {
  if (refreshPromise) {
    return refreshPromise;
  }
  const current = readTokenPair();
  if (!current) {
    return null;
  }

  refreshPromise = (async () => {
    try {
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ refresh_token: current.refresh_token }),
      });
      if (!response.ok) {
        clearTokenPair();
        notifyAuthExpired();
        return null;
      }
      const pair = (await response.json()) as TokenPair;
      writeTokenPair(pair);
      return pair;
    } catch {
      clearTokenPair();
      notifyAuthExpired();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

async function parseApiError(response: Response): Promise<ApiError> {
  let payload: PlatformErrorBody | null = null;
  try {
    payload = (await response.json()) as PlatformErrorBody;
  } catch {
    payload = null;
  }
  const code = payload?.error?.code || `http_${response.status}`;
  const message = payload?.error?.message || safeStatusMessage(response.status);
  return new ApiError({
    status: response.status,
    code,
    message,
    requestId: payload?.request_id || response.headers.get("X-Request-ID"),
    details: payload?.error?.details ?? payload?.detail,
  });
}

function safeStatusMessage(status: number): string {
  if (status === 401) return "登录状态已失效，请重新登录。";
  if (status === 403) return "当前角色无权执行此操作。";
  if (status === 404) return "资源不存在或当前账号无权查看。";
  if (status === 409) return "当前数据状态发生冲突，请刷新后重试。";
  if (status === 422) return "提交内容未通过校验。";
  if (status === 429) return "请求过于频繁，请稍后再试。";
  if (status >= 500) return "服务暂时不可用，请稍后再试。";
  return "请求失败。";
}

async function performRequest(
  path: string,
  init: RequestInit,
  options: Required<RequestOptions>,
): Promise<Response> {
  const execute = () =>
    fetch(`${API_BASE}${path}`, {
      ...init,
      headers: headersFor(init, options.auth),
    });

  let response: Response;
  try {
    response = await execute();
  } catch (error) {
    throw new ApiError({
      status: 0,
      code: "network_error",
      message: "无法连接 FastAPI，请确认后端服务已经启动。",
      details: error,
    });
  }

  if (
    response.status === 401 &&
    options.auth &&
    options.retryOnUnauthorized &&
    (await refreshTokens())
  ) {
    response = await execute();
  }

  if (!response.ok) {
    if (response.status === 401 && options.auth) {
      clearTokenPair();
      notifyAuthExpired();
    }
    throw await parseApiError(response);
  }
  return response;
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const response = await performRequest(path, init, {
    auth: options.auth ?? true,
    retryOnUnauthorized: options.retryOnUnauthorized ?? true,
  });
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function apiBlob(
  path: string,
  init: RequestInit = {},
): Promise<Blob> {
  const response = await performRequest(path, init, {
    auth: true,
    retryOnUnauthorized: true,
  });
  return response.blob();
}

export async function apiStreamResponse(
  path: string,
  init: RequestInit,
): Promise<Response> {
  return performRequest(
    path,
    {
      ...init,
      headers: {
        ...Object.fromEntries(new Headers(init.headers).entries()),
        Accept: "text/event-stream",
      },
    },
    { auth: true, retryOnUnauthorized: true },
  );
}

export function onAuthExpired(listener: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  window.addEventListener(AUTH_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
}
