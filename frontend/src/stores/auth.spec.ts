import { createPinia, setActivePinia } from "pinia";
import { beforeEach, vi } from "vitest";

const { login, me, logout } = vi.hoisted(() => ({
  login: vi.fn(),
  me: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({ authApi: { login, me, logout } }));

import { readTokenPair } from "@/auth/session";
import { useAuthStore } from "@/stores/auth";

describe("auth store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("stores both tokens and then loads the current user", async () => {
    login.mockResolvedValueOnce({ access_token: "access", refresh_token: "refresh", token_type: "bearer", expires_in: 900 });
    me.mockResolvedValueOnce({ id: "user-1", tenant_id: "tenant-1", username: "demo", email: "demo@example.com", roles: ["user"] });
    const store = useAuthStore();
    await store.login({ tenantId: " tenant-1 ", username: " demo ", password: "not-a-real-password" });
    expect(login).toHaveBeenCalledWith({ tenant_id: "tenant-1", username: "demo", password: "not-a-real-password" });
    expect(store.user?.username).toBe("demo");
    expect(readTokenPair()).toMatchObject({ access_token: "access", refresh_token: "refresh" });
  });

  it("clears the session when loading the current user fails", async () => {
    login.mockResolvedValueOnce({ access_token: "access-2", refresh_token: "refresh-2", token_type: "bearer", expires_in: 900 });
    me.mockRejectedValueOnce(new Error("unauthorized"));
    const store = useAuthStore();
    await expect(store.login({ tenantId: "tenant", username: "demo", password: "not-a-real-password" })).rejects.toThrow("unauthorized");
    expect(store.user).toBeNull();
    expect(readTokenPair()).toBeNull();
  });
});
