<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@/api/client";
import { ticketApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { CustomerTicketDetail, ReplySuggestion, TicketClassification } from "@/types/api";
import {
  formatDateTime,
  formatPercent,
  ticketCategoryLabel,
  ticketPriorityLabel,
  ticketStatusLabel,
} from "@/ui/formatters";

const route = useRoute();
const router = useRouter();
const detail = ref<CustomerTicketDetail | null>(null);
const classification = ref<TicketClassification | null>(null);
const suggestion = ref<ReplySuggestion | null>(null);
const finalReply = ref("");
const loading = ref(false);
const action = ref<"classify" | "suggest" | "confirm" | null>(null);
const error = ref<ApiError | null>(null);
const success = ref("");
const ticketId = computed(() => String(route.params.ticketId || ""));

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    detail.value = await ticketApi.get(ticketId.value);
    if (detail.value.view === "internal") {
      suggestion.value = detail.value.reply_suggestion;
      finalReply.value = suggestion.value?.final_reply || suggestion.value?.suggested_reply || "";
    }
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "工单详情加载失败。" });
  } finally {
    loading.value = false;
  }
}

async function classify(): Promise<void> {
  action.value = "classify"; error.value = null; success.value = "";
  try {
    classification.value = await ticketApi.classify(ticketId.value);
    success.value = "AI 分类已保存，可继续生成回复建议。";
    await load();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "AI 分类失败。" });
  } finally { action.value = null; }
}

async function suggest(): Promise<void> {
  action.value = "suggest"; error.value = null; success.value = "";
  try {
    suggestion.value = await ticketApi.suggest(ticketId.value);
    finalReply.value = suggestion.value.suggested_reply;
    success.value = "AI 建议已生成，请人工核对后确认。";
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "回复建议生成失败。" });
  } finally { action.value = null; }
}

async function confirmReply(): Promise<void> {
  if (!suggestion.value || suggestion.value.status !== "draft" || !finalReply.value.trim()) return;
  action.value = "confirm"; error.value = null; success.value = "";
  try {
    detail.value = await ticketApi.confirm(suggestion.value.id, finalReply.value.trim());
    success.value = "回复已由人工确认并保存。";
    await load();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "人工确认失败。" });
  } finally { action.value = null; }
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader title="工单处理台" description="AI 仅提供分类和回复草稿；客服人员对最终回复承担确认责任。">
      <button class="secondary-button" type="button" @click="router.push('/service/tickets')">返回列表</button>
      <button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button>
    </PageHeader>
    <StatusPanel v-if="error" title="操作失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <StatusPanel v-if="success" title="操作完成" :description="success" tone="success" />
    <p v-if="loading" class="card muted">正在加载…</p>
    <template v-else-if="detail">
      <article class="card ticket-summary">
        <div>
          <p class="eyebrow">工单 {{ detail.ticket.id }}</p>
          <h3>{{ detail.ticket.subject }}</h3>
          <p class="description">{{ detail.ticket.description }}</p>
        </div>
        <div class="tag-row">
          <span class="tag">{{ ticketStatusLabel(detail.ticket.status) }}</span>
          <span class="tag">{{ ticketCategoryLabel(detail.ticket.category) }}</span>
          <span class="tag">{{ ticketPriorityLabel(detail.ticket.priority) }}优先级</span>
        </div>
        <small>创建：{{ formatDateTime(detail.ticket.created_at) }}　更新：{{ formatDateTime(detail.ticket.updated_at) }}</small>
      </article>

      <StatusPanel v-if="detail.view !== 'internal'" title="当前账号只能查看公开工单信息" description="客服处理功能仅对 customer_service 角色开放。" tone="warning" />

      <template v-else>
        <div class="action-grid">
          <article class="card action-card">
            <h3>第一步：AI 分类</h3>
            <p>根据工单内容识别业务分类、优先级和置信度。</p>
            <button class="primary-button" type="button" :disabled="action !== null" @click="classify">{{ action === 'classify' ? '分类中…' : '执行 AI 分类' }}</button>
            <div v-if="classification" class="result-box">
              <strong>{{ ticketCategoryLabel(classification.category) }} · {{ ticketPriorityLabel(classification.priority) }}</strong>
              <span>置信度 {{ formatPercent(classification.confidence) }}</span>
              <p>{{ classification.reason }}</p>
            </div>
          </article>

          <article class="card action-card">
            <h3>第二步：生成回复建议</h3>
            <p>结合分类和知识库形成可编辑草稿，不会自动发送。</p>
            <button class="primary-button" type="button" :disabled="action !== null" @click="suggest">{{ action === 'suggest' ? '生成中…' : '生成 AI 建议' }}</button>
            <div v-if="suggestion" class="result-box">
              <span>质量：{{ suggestion.quality_status === 'passed' ? '通过' : '需复核' }} · 知识结果：{{ suggestion.knowledge_outcome }}</span>
              <ul v-if="suggestion.quality_notes.length"><li v-for="note in suggestion.quality_notes" :key="note">{{ note }}</li></ul>
            </div>
          </article>
        </div>

        <article v-if="suggestion" class="card confirm-card">
          <h3>第三步：人工确认</h3>
          <label>最终回复<textarea v-model="finalReply" maxlength="10000" :disabled="suggestion.status !== 'draft'" /></label>
          <div v-if="suggestion.citations.length" class="citations">
            <strong>知识依据</strong>
            <article v-for="citation in suggestion.citations" :key="`${citation.document_name}-${citation.rank || 0}`"><b>{{ citation.document_name }}</b><p>{{ citation.excerpt }}</p></article>
          </div>
          <button class="primary-button" type="button" :disabled="action !== null || suggestion.status !== 'draft' || !finalReply.trim()" @click="confirmReply">
            {{ suggestion.status === 'confirmed' ? '已确认' : action === 'confirm' ? '确认中…' : '确认最终回复' }}
          </button>
        </article>
      </template>
    </template>
  </section>
</template>

<style scoped>
.muted { color: var(--muted); }
.ticket-summary { display: grid; gap: 13px; }
.ticket-summary h3 { margin: 6px 0; font-size: 22px; }
.ticket-summary .description { white-space: pre-wrap; line-height: 1.75; }
.ticket-summary small { color: var(--muted); }
.action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.action-card { display: grid; align-content: start; gap: 12px; }
.action-card h3, .action-card p { margin: 0; }
.action-card > p { min-height: 48px; color: var(--muted); line-height: 1.6; }
.action-card .primary-button { justify-self: start; }
.result-box { display: grid; gap: 8px; padding: 13px; border: 1px solid var(--line); border-radius: 12px; background: #f8fafc; }
.result-box p, .result-box ul { margin: 0; color: #475467; line-height: 1.6; }
.confirm-card { display: grid; gap: 16px; }
.confirm-card h3 { margin: 0; }
.confirm-card .primary-button { justify-self: start; }
.citations { display: grid; gap: 9px; }
.citations article { padding: 12px; border: 1px solid var(--line); border-radius: 11px; }
.citations p { margin: 6px 0 0; color: var(--muted); }
@media (max-width: 850px) { .action-grid { grid-template-columns: 1fr; } }
</style>
