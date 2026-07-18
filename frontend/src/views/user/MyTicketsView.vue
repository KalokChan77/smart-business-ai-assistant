<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError } from "@/api/client";
import { ticketApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { CustomerTicket, CustomerTicketDetail } from "@/types/api";
import { formatDateTime, ticketCategoryLabel, ticketPriorityLabel, ticketStatusLabel } from "@/ui/formatters";

const tickets = ref<CustomerTicket[]>([]);
const subject = ref("");
const description = ref("");
const loading = ref(false);
const submitting = ref(false);
const detailLoading = ref(false);
const error = ref<ApiError | null>(null);
const success = ref("");
const selectedDetail = ref<CustomerTicketDetail | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    tickets.value = (await ticketApi.list({ limit: 100 })).items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "工单加载失败。" });
  } finally {
    loading.value = false;
  }
}

async function createTicket(): Promise<void> {
  if (!subject.value.trim() || !description.value.trim() || submitting.value) return;
  submitting.value = true;
  error.value = null;
  success.value = "";
  try {
    await ticketApi.create(subject.value.trim(), description.value.trim());
    subject.value = "";
    description.value = "";
    success.value = "工单已提交，客服人员将在处理后确认回复。";
    await load();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "工单提交失败。" });
  } finally {
    submitting.value = false;
  }
}

async function viewTicket(ticketId: string): Promise<void> {
  detailLoading.value = true;
  error.value = null;
  selectedDetail.value = null;
  try {
    selectedDetail.value = await ticketApi.get(ticketId);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "工单详情加载失败。" });
  } finally {
    detailLoading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader title="我的工单" description="提交需要人工处理的问题，并查看工单状态与客服最终确认的回复。">
      <button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button>
    </PageHeader>

    <form class="card ticket-form" @submit.prevent="createTicket">
      <h3>创建新工单</h3>
      <label>主题<input v-model="subject" maxlength="200" placeholder="简要概括问题" /></label>
      <label>问题描述<textarea v-model="description" maxlength="10000" placeholder="请描述问题、发生时间和期望结果" /></label>
      <button class="primary-button" type="submit" :disabled="submitting || !subject.trim() || !description.trim()">{{ submitting ? "提交中…" : "提交工单" }}</button>
    </form>

    <StatusPanel v-if="error" title="操作失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <StatusPanel v-if="success" title="提交成功" :description="success" tone="success" />

    <div class="card">
      <h3>工单记录</h3>
      <p v-if="loading" class="muted">正在加载…</p>
      <p v-else-if="tickets.length === 0" class="muted">暂无工单。</p>
      <div v-else class="ticket-list">
        <article v-for="ticket in tickets" :key="ticket.id" class="ticket-item">
          <div>
            <strong>{{ ticket.subject }}</strong>
            <p>{{ ticket.description }}</p>
            <small>{{ formatDateTime(ticket.created_at) }}</small>
          </div>
          <div class="ticket-meta">
            <span class="tag">{{ ticketStatusLabel(ticket.status) }}</span>
            <span>{{ ticketCategoryLabel(ticket.category) }}</span>
            <span>{{ ticketPriorityLabel(ticket.priority) }}优先级</span>
            <button class="secondary-button" type="button" :disabled="detailLoading" @click="viewTicket(ticket.id)">查看详情</button>
          </div>
        </article>
      </div>
    </div>

    <article v-if="selectedDetail" class="card ticket-detail-card">
      <div class="answer-heading">
        <div>
          <p class="eyebrow">工单详情</p>
          <h3>{{ selectedDetail.ticket.subject }}</h3>
        </div>
        <span class="tag">{{ ticketStatusLabel(selectedDetail.ticket.status) }}</span>
      </div>
      <template v-if="selectedDetail.view === 'public' && selectedDetail.confirmed_reply">
        <h4>客服最终回复</h4>
        <p class="confirmed-reply">{{ selectedDetail.confirmed_reply.final_reply }}</p>
        <small>确认时间：{{ formatDateTime(selectedDetail.confirmed_reply.confirmed_at) }}</small>
      </template>
      <StatusPanel
        v-else
        title="客服尚未确认最终回复"
        description="工单正在处理中，请稍后刷新后再次查看。"
        tone="warning"
      />
    </article>
  </section>
</template>

<style scoped>
.ticket-form { display: grid; gap: 15px; }
.ticket-form h3, .card > h3 { margin-top: 0; }
.ticket-form .primary-button { justify-self: start; }
.muted { color: var(--muted); }
.ticket-list { display: grid; gap: 12px; }
.ticket-item { display: flex; justify-content: space-between; gap: 18px; padding: 16px; border: 1px solid var(--line); border-radius: 14px; }
.ticket-item p { max-width: 760px; margin: 8px 0; color: #475467; white-space: pre-wrap; }
.ticket-item small, .ticket-meta { color: var(--muted); }
.ticket-meta { display: grid; min-width: 130px; align-content: start; justify-items: end; gap: 8px; font-size: 13px; }
.ticket-meta .secondary-button { padding: 7px 10px; }
.ticket-detail-card { display: grid; gap: 14px; }
.answer-heading { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.answer-heading h3, .answer-heading p, .ticket-detail-card h4 { margin: 0; }
.confirmed-reply { margin: 0; white-space: pre-wrap; line-height: 1.75; }
.ticket-detail-card > small { color: var(--muted); }
@media (max-width: 720px) { .ticket-item { flex-direction: column; } .ticket-meta { justify-items: start; } }
</style>
