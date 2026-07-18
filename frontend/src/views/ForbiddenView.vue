<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import { defaultPathForRoles } from "@/router/navigation";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();
const router = useRouter();
const home = computed(() => defaultPathForRoles(auth.roles, auth.user?.id));
</script>

<template>
  <main class="standalone-state">
    <div class="state-code">403</div>
    <h1>当前角色无权访问</h1>
    <p>页面入口和后端权限都会进行校验。请返回自己有权限的工作台。</p>
    <button class="primary-button" type="button" @click="router.replace(home)">返回工作台</button>
  </main>
</template>
