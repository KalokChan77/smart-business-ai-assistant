<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import {
  availableWorkspaces,
  navigationForRoles,
  rememberWorkspace,
  roleForPath,
} from "@/router/navigation";
import { useAuthStore } from "@/stores/auth";
import type { RoleCode } from "@/types/api";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const mobileOpen = ref(false);

const navItems = computed(() => navigationForRoles(auth.roles));
const workspaceOptions = computed(() => availableWorkspaces(auth.roles));
const activeWorkspace = computed(() => roleForPath(route.path) ?? auth.roles[0] ?? "user");

watch(
  () => route.fullPath,
  () => {
    mobileOpen.value = false;
  },
);

async function switchWorkspace(event: Event) {
  const role = (event.target as HTMLSelectElement).value as RoleCode;
  const workspace = workspaceOptions.value.find((item) => item.role === role);
  if (!workspace || !auth.user) return;
  rememberWorkspace(auth.user.id, role);
  await router.push(workspace.defaultPath);
}

async function logout() {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <div class="app-shell">
    <button
      class="mobile-nav-button"
      type="button"
      aria-label="打开或关闭导航"
      @click="mobileOpen = !mobileOpen"
    >
      ☰
    </button>
    <aside class="app-sidebar" :class="{ 'is-open': mobileOpen }">
      <div class="brand-block">
        <div class="brand-mark">智</div>
        <div>
          <strong>智慧商务 AI</strong>
          <span>本地教学演示</span>
        </div>
      </div>

      <label class="workspace-select">
        <span>当前工作台</span>
        <select :value="activeWorkspace" @change="switchWorkspace">
          <option v-for="workspace in workspaceOptions" :key="workspace.role" :value="workspace.role">
            {{ workspace.label }}
          </option>
        </select>
      </label>

      <nav aria-label="主导航">
        <RouterLink
          v-for="item in navItems.filter((entry) => entry.section === 'workspace')"
          :key="item.to"
          class="nav-link"
          :to="item.to"
        >
          <span class="nav-marker">{{ item.marker }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-footer">
        <RouterLink
          v-for="item in navItems.filter((entry) => entry.section === 'account')"
          :key="item.to"
          class="nav-link"
          :to="item.to"
        >
          <span class="nav-marker">{{ item.marker }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
        <button class="nav-link nav-button" type="button" @click="logout">
          <span class="nav-marker">退</span>
          <span>退出登录</span>
        </button>
      </div>
    </aside>

    <div v-if="mobileOpen" class="sidebar-backdrop" @click="mobileOpen = false" />

    <main class="app-main">
      <header class="app-topbar">
        <div>
          <p class="eyebrow">{{ route.meta.title }}</p>
          <h1>{{ route.meta.title || "工作台" }}</h1>
        </div>
        <div v-if="auth.user" class="user-summary">
          <span>{{ auth.user.username }}</span>
          <small>{{ auth.user.email }}</small>
        </div>
      </header>
      <div class="app-content">
        <RouterView />
      </div>
    </main>
  </div>
</template>
