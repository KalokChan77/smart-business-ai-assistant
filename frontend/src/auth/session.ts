import type { TokenPair } from "@/types/api";

const SESSION_KEY = "smart-business-ai.auth.v1";

function storage(): Storage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.sessionStorage;
}

export function readTokenPair(): TokenPair | null {
  const raw = storage()?.getItem(SESSION_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as Partial<TokenPair>;
    if (
      typeof parsed.access_token !== "string" ||
      typeof parsed.refresh_token !== "string" ||
      typeof parsed.expires_in !== "number"
    ) {
      clearTokenPair();
      return null;
    }
    return {
      access_token: parsed.access_token,
      refresh_token: parsed.refresh_token,
      token_type: "bearer",
      expires_in: parsed.expires_in,
    };
  } catch {
    clearTokenPair();
    return null;
  }
}

export function writeTokenPair(pair: TokenPair): void {
  storage()?.setItem(SESSION_KEY, JSON.stringify(pair));
}

export function clearTokenPair(): void {
  storage()?.removeItem(SESSION_KEY);
}
