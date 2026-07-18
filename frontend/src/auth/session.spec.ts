import { clearTokenPair, readTokenPair, writeTokenPair } from "@/auth/session";
import type { TokenPair } from "@/types/api";

const pair: TokenPair = {
  access_token: "test-access-token",
  refresh_token: "test-refresh-token",
  token_type: "bearer",
  expires_in: 900,
};

describe("token session", () => {
  it("writes and reads a complete token pair", () => {
    writeTokenPair(pair);
    expect(readTokenPair()).toEqual(pair);
  });

  it("clears corrupted JSON without exposing it", () => {
    window.sessionStorage.setItem("smart-business-ai.auth.v1", "{broken");
    expect(readTokenPair()).toBeNull();
    expect(window.sessionStorage.getItem("smart-business-ai.auth.v1")).toBeNull();
  });

  it("rejects an incomplete token pair", () => {
    window.sessionStorage.setItem(
      "smart-business-ai.auth.v1",
      JSON.stringify({ access_token: "only-access", expires_in: 60 }),
    );
    expect(readTokenPair()).toBeNull();
    clearTokenPair();
  });
});

