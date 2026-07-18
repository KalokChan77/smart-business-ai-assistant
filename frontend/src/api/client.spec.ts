import { apiRequest } from "@/api/client";
import { readTokenPair, writeTokenPair } from "@/auth/session";

describe("API client", () => {
  it("does not parse a 204 response body", async () => {
    const json = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 204, json }));
    await expect(apiRequest<void>("/empty")).resolves.toBeUndefined();
    expect(json).not.toHaveBeenCalled();
  });

  it("deduplicates concurrent refreshes and replays requests with the new access token", async () => {
    writeTokenPair({ access_token: "old-access", refresh_token: "old-refresh", token_type: "bearer", expires_in: 10 });
    let protectedCalls = 0;
    let refreshCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshCalls += 1;
        await Promise.resolve();
        return new Response(JSON.stringify({ access_token: "new-access", refresh_token: "new-refresh", token_type: "bearer", expires_in: 900 }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      protectedCalls += 1;
      const auth = new Headers(init?.headers).get("Authorization");
      if (auth === "Bearer old-access") return new Response("", { status: 401 });
      expect(auth).toBe("Bearer new-access");
      return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(Promise.all([apiRequest("/one"), apiRequest("/two")])).resolves.toEqual([{ ok: true }, { ok: true }]);
    expect(refreshCalls).toBe(1);
    expect(protectedCalls).toBe(4);
    expect(readTokenPair()).toMatchObject({ access_token: "new-access", refresh_token: "new-refresh" });
  });

  it("parses the platform error code, message and request id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "validation_error", message: "输入不合法。" }, request_id: "request-1" }), { status: 422, headers: { "Content-Type": "application/json" } })));
    await expect(apiRequest("/invalid", {}, { auth: false })).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "输入不合法。",
      requestId: "request-1",
    });
  });
});

