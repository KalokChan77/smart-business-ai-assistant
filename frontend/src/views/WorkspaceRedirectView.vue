<script setup lang="ts">
import { onMounted } from "vue";
import { useRouter } from "vue-router";

import { defaultPathForRoles } from "@/router/navigation";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const auth = useAuthStore();

onMounted(() => {
  if (auth.user) {
    void router.replace(defaultPathForRoles(auth.roles, auth.user.id));
  }
});
</script>

<template>
  <div class="center-stage">正在进入工作台…</div>
</template>
