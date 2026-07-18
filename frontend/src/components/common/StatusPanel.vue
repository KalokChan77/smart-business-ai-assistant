<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
  tone?: "neutral" | "danger" | "success" | "warning";
  requestId?: string | null;
}>();
</script>

<template>
  <div class="status-panel" :class="`tone-${tone || 'neutral'}`" role="status">
    <strong>{{ title }}</strong>
    <p v-if="description">{{ description }}</p>
    <small v-if="requestId">请求编号：{{ requestId }}</small>
    <div v-if="$slots.default" class="status-actions"><slot /></div>
  </div>
</template>
