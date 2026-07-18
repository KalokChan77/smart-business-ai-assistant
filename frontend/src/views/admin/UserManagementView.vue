<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError } from "@/api/client";
import { usersApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { RoleCode, UserAccount } from "@/types/api";
import { formatDateTime } from "@/ui/formatters";

const roleOptions: Array<{ code: RoleCode; label: string }> = [
  { code: "user", label: "企业用户" }, { code: "customer_service", label: "客服人员" },
  { code: "decision_maker", label: "决策者" }, { code: "admin", label: "管理员" },
];
const users = ref<UserAccount[]>([]);
const username = ref("");
const email = ref("");
const password = ref("");
const roles = ref<RoleCode[]>(["user"]);
const loading = ref(false);
const submitting = ref(false);
const updatingId = ref<string | null>(null);
const error = ref<ApiError | null>(null);
const success = ref("");

async function load(): Promise<void> {
  loading.value = true; error.value = null;
  try { users.value = await usersApi.list(); }
  catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "用户加载失败。" }); }
  finally { loading.value = false; }
}

function toggleCreateRole(role: RoleCode): void {
  roles.value = roles.value.includes(role) ? roles.value.filter((item) => item !== role) : [...roles.value, role];
}

async function createUser(): Promise<void> {
  if (!username.value.trim() || !email.value.trim() || password.value.length < 8 || roles.value.length === 0) return;
  submitting.value = true; error.value = null; success.value = "";
  try {
    await usersApi.create({ username: username.value.trim(), email: email.value.trim(), password: password.value, role_codes: roles.value });
    username.value = ""; email.value = ""; password.value = ""; roles.value = ["user"];
    success.value = "用户创建成功。";
    await load();
  } catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "用户创建失败。" }); }
  finally { submitting.value = false; }
}

async function toggleStatus(user: UserAccount): Promise<void> {
  updatingId.value = user.id; error.value = null; success.value = "";
  try {
    await usersApi.update(user.id, { status: user.status === "active" ? "disabled" : "active" });
    success.value = `账号 ${user.username} 状态已更新。`;
    await load();
  } catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "账号状态更新失败。" }); }
  finally { updatingId.value = null; }
}

async function toggleUserRole(user: UserAccount, role: RoleCode): Promise<void> {
  const next = user.roles.includes(role) ? user.roles.filter((item) => item !== role) : [...user.roles, role];
  if (next.length === 0) { error.value = new ApiError({ status: 0, code: "role_required", message: "用户至少需要保留一个角色。" }); return; }
  updatingId.value = user.id; error.value = null; success.value = "";
  try {
    await usersApi.update(user.id, { role_codes: next });
    success.value = `账号 ${user.username} 的角色已更新。`;
    await load();
  } catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "角色更新失败。" }); }
  finally { updatingId.value = null; }
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader title="用户与角色" description="管理员只能管理当前租户账号；权限仍由 FastAPI 在每个接口上校验。"><button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button></PageHeader>
    <StatusPanel v-if="error" title="操作失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <StatusPanel v-if="success" title="操作成功" :description="success" tone="success" />
    <form class="card create-form" @submit.prevent="createUser">
      <h3>创建租户用户</h3>
      <div class="form-grid"><label>用户名<input v-model="username" maxlength="64" autocomplete="off" /></label><label>邮箱<input v-model="email" type="email" maxlength="255" /></label><label>初始密码<input v-model="password" type="password" minlength="8" maxlength="128" autocomplete="new-password" /></label></div>
      <div class="role-picker"><span>角色</span><label v-for="item in roleOptions" :key="item.code"><input type="checkbox" :checked="roles.includes(item.code)" @change="toggleCreateRole(item.code)" />{{ item.label }}</label></div>
      <button class="primary-button" type="submit" :disabled="submitting || !username.trim() || !email.trim() || password.length < 8 || roles.length === 0">{{ submitting ? "创建中…" : "创建用户" }}</button>
    </form>
    <div class="card">
      <p v-if="loading" class="muted">正在加载…</p>
      <div v-else class="user-list">
        <article v-for="user in users" :key="user.id" class="user-row">
          <div><strong>{{ user.username }}</strong><p>{{ user.email }}</p><small>创建于 {{ formatDateTime(user.created_at) }}</small></div>
          <div class="role-picker inline"><label v-for="item in roleOptions" :key="item.code"><input type="checkbox" :checked="user.roles.includes(item.code)" :disabled="updatingId === user.id" @change="toggleUserRole(user, item.code)" />{{ item.label }}</label></div>
          <button :class="user.status === 'active' ? 'danger-button' : 'secondary-button'" type="button" :disabled="updatingId === user.id" @click="toggleStatus(user)">{{ user.status === 'active' ? '停用' : '启用' }}</button>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.create-form { display: grid; gap: 16px; }
.create-form h3 { margin: 0; }
.form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; }
.create-form > .primary-button { justify-self: start; }
.role-picker { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.role-picker > span { color: #344054; font-weight: 700; }
.role-picker label { display: flex; grid-template-columns: auto 1fr; align-items: center; gap: 5px; font-weight: 500; }
.role-picker input { width: auto; }
.user-list { display: grid; gap: 11px; }
.user-row { display: grid; grid-template-columns: minmax(180px, .8fr) minmax(320px, 1.5fr) auto; align-items: center; gap: 16px; padding: 15px; border: 1px solid var(--line); border-radius: 13px; }
.user-row p { margin: 5px 0; color: #475467; }
.user-row small, .muted { color: var(--muted); }
@media (max-width: 900px) { .form-grid, .user-row { grid-template-columns: 1fr; } }
</style>

