import { defineStore } from "pinia";

import { authApi } from "@/api/endpoints";
import { clearTokenPair, readTokenPair, writeTokenPair } from "@/auth/session";
import type { CurrentUser, RoleCode } from "@/types/api";

interface AuthState {
  user: CurrentUser | null;
  initialized: boolean;
  busy: boolean;
}

export const useAuthStore = defineStore("auth", {
  state: (): AuthState => ({
    user: null,
    initialized: false,
    busy: false,
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
    roles: (state): RoleCode[] => state.user?.roles ?? [],
    hasRole: (state) => (role: RoleCode) => state.user?.roles.includes(role) ?? false,
  },
  actions: {
    async login(payload: { tenantId: string; username: string; password: string }) {
      this.busy = true;
      try {
        const pair = await authApi.login({
          tenant_id: payload.tenantId.trim(),
          username: payload.username.trim(),
          password: payload.password,
        });
        writeTokenPair(pair);
        this.user = await authApi.me();
        this.initialized = true;
        return this.user;
      } catch (error) {
        this.clear();
        this.initialized = true;
        throw error;
      } finally {
        this.busy = false;
      }
    },
    async restore() {
      if (this.initialized) {
        return;
      }
      if (!readTokenPair()) {
        this.initialized = true;
        return;
      }
      this.busy = true;
      try {
        this.user = await authApi.me();
      } catch {
        this.clear();
      } finally {
        this.busy = false;
        this.initialized = true;
      }
    },
    async logout() {
      const pair = readTokenPair();
      try {
        if (pair) {
          await authApi.logout(pair.refresh_token);
        }
      } finally {
        this.clear();
      }
    },
    clear() {
      clearTokenPair();
      this.user = null;
    },
  },
});
