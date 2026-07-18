<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError } from "@/api/client";
import { conversationApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { Conversation, ConversationMessage } from "@/types/api";
import { formatDateTime } from "@/ui/formatters";

const conversations = ref<Conversation[]>([]);
const messages = ref<ConversationMessage[]>([]);
const selected = ref<Conversation | null>(null);
const loading = ref(false);
const loadingMessages = ref(false);
const error = ref<ApiError | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    conversations.value = (await conversationApi.list(100)).items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "会话加载失败。" });
  } finally {
    loading.value = false;
  }
}

async function openConversation(item: Conversation): Promise<void> {
  selected.value = item;
  loadingMessages.value = true;
  error.value = null;
  try {
    messages.value = (await conversationApi.messages(item.id)).items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "消息加载失败。" });
  } finally {
    loadingMessages.value = false;
  }
}

async function remove(item: Conversation): Promise<void> {
  if (!window.confirm(`确认删除会话“${item.title}”吗？`)) return;
  error.value = null;
  try {
    await conversationApi.remove(item.id);
    if (selected.value?.id === item.id) {
      selected.value = null;
      messages.value = [];
    }
    await load();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "会话删除失败。" });
  }
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader title="历史会话" description="查看已持久化的用户消息与完整 AI 回答；流式失败时不会保存残缺助手消息。">
      <button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button>
    </PageHeader>
    <StatusPanel v-if="error" title="操作失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <div class="conversation-layout">
      <aside class="card conversation-list">
        <p v-if="loading" class="muted">正在加载…</p>
        <p v-else-if="conversations.length === 0" class="muted">暂无历史会话。</p>
        <article v-for="item in conversations" v-else :key="item.id" :class="['conversation-row', { active: selected?.id === item.id }]">
          <button type="button" @click="openConversation(item)">
            <strong>{{ item.title }}</strong>
            <small>{{ formatDateTime(item.last_message_at || item.created_at) }}</small>
          </button>
          <button class="delete-link" type="button" title="删除会话" @click="remove(item)">删除</button>
        </article>
      </aside>
      <main class="card message-panel">
        <p v-if="!selected" class="muted">选择左侧会话查看消息。</p>
        <p v-else-if="loadingMessages" class="muted">正在加载消息…</p>
        <template v-else>
          <h3>{{ selected?.title }}</h3>
          <div class="message-list">
            <article v-for="message in messages" :key="message.id" :class="['message-bubble', `role-${message.role}`]">
              <strong>{{ message.role === 'user' ? '我' : message.role === 'assistant' ? 'AI 助手' : message.role }}</strong>
              <p>{{ message.content }}</p>
              <small>{{ formatDateTime(message.created_at) }}</small>
            </article>
          </div>
        </template>
      </main>
    </div>
  </section>
</template>

<style scoped>
.conversation-layout { display: grid; grid-template-columns: minmax(250px, 0.34fr) minmax(0, 0.66fr); gap: 18px; }
.conversation-list, .message-panel { min-height: 460px; }
.conversation-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; margin-bottom: 8px; border: 1px solid var(--line); border-radius: 12px; }
.conversation-row.active { border-color: var(--blue); background: var(--blue-soft); }
.conversation-row > button:first-child { display: grid; gap: 5px; padding: 12px; border: 0; text-align: left; background: transparent; cursor: pointer; }
.conversation-row small, .muted { color: var(--muted); }
.delete-link { padding: 8px; border: 0; color: var(--red); background: transparent; cursor: pointer; }
.message-panel h3 { margin-top: 0; }
.message-list { display: grid; gap: 12px; }
.message-bubble { max-width: 84%; padding: 14px; border-radius: 15px; background: #f1f5f9; }
.message-bubble.role-user { justify-self: end; background: var(--blue-soft); }
.message-bubble p { margin: 7px 0; white-space: pre-wrap; line-height: 1.65; }
.message-bubble small { color: var(--muted); }
@media (max-width: 820px) { .conversation-layout { grid-template-columns: 1fr; } }
</style>
