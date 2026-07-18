<script setup lang="ts">
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
</script>

<template>
  <section v-if="auth.user" class="content-stack">
    <div class="profile-card">
      <div class="profile-avatar">{{ auth.user.username.slice(0, 1).toUpperCase() }}</div>
      <div>
        <p class="eyebrow">当前账号</p>
        <h2>{{ auth.user.username }}</h2>
        <p>{{ auth.user.email }}</p>
      </div>
    </div>
    <div class="detail-grid">
      <article class="detail-card">
        <span>用户 ID</span>
        <code>{{ auth.user.id }}</code>
      </article>
      <article class="detail-card">
        <span>租户 ID</span>
        <code>{{ auth.user.tenant_id }}</code>
      </article>
      <article class="detail-card">
        <span>当前角色</span>
        <div class="tag-row">
          <span v-for="role in auth.user.roles" :key="role" class="tag">{{ role }}</span>
        </div>
      </article>
    </div>
  </section>
</template>
