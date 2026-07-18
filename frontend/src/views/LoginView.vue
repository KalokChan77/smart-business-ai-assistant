<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@/api/client";
import { defaultPathForRoles } from "@/router/navigation";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const errorMessage = ref("");
const requestId = ref<string | null>(null);
const form = reactive({
  tenantId: "",
  username: "",
  password: "",
});

async function submit() {
  errorMessage.value = "";
  requestId.value = null;
  try {
    const user = await auth.login(form);
    const requested = typeof route.query.redirect === "string" ? route.query.redirect : null;
    const fallback = defaultPathForRoles(user.roles, user.id);
    await router.replace(requested && requested.startsWith("/") ? requested : fallback);
  } catch (error) {
    const apiError = error instanceof ApiError ? error : null;
    errorMessage.value = apiError?.message || "登录失败，请检查输入后重试。";
    requestId.value = apiError?.requestId ?? null;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-hero">
      <div class="brand-mark large">智</div>
      <p class="eyebrow">Vue3 · FastAPI · LangGraph · Dify</p>
      <h1>智慧商务 AI 助手平台</h1>
      <p>
        面向企业用户、客服人员、管理员和决策者的本地教学演示系统。所有 AI 与知识库请求均通过 FastAPI 安全网关完成。
      </p>
      <ul>
        <li>流式 AI 对话与业务工具调用</li>
        <li>企业知识库问答与引用</li>
        <li>客服建议回复与人工确认</li>
        <li>租户统计与 AI 质量分析</li>
      </ul>
    </section>

    <section class="login-card" aria-labelledby="login-title">
      <p class="eyebrow">本地演示入口</p>
      <h2 id="login-title">登录工作台</h2>
      <form @submit.prevent="submit">
        <label>
          <span>租户 ID</span>
          <input
            v-model="form.tenantId"
            name="tenant_id"
            autocomplete="organization"
            placeholder="请输入租户 UUID"
            required
          />
        </label>
        <label>
          <span>用户名</span>
          <input
            v-model="form.username"
            name="username"
            autocomplete="username"
            placeholder="例如 admin"
            required
          />
        </label>
        <label>
          <span>密码</span>
          <input
            v-model="form.password"
            name="password"
            type="password"
            autocomplete="current-password"
            minlength="8"
            required
          />
        </label>
        <div v-if="errorMessage" class="form-error" role="alert">
          <strong>{{ errorMessage }}</strong>
          <small v-if="requestId">请求编号：{{ requestId }}</small>
        </div>
        <button class="primary-button wide" type="submit" :disabled="auth.busy">
          {{ auth.busy ? "正在验证…" : "登录" }}
        </button>
      </form>
      <p class="security-note">令牌只保存在当前标签页会话中，退出或会话失效后会立即清理。</p>
    </section>
  </main>
</template>
