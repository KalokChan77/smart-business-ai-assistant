<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "@/api/client";
import { ticketApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { CustomerTicket, TicketCategory, TicketStatus } from "@/types/api";
import { formatDateTime, ticketCategoryLabel, ticketPriorityLabel, ticketStatusLabel } from "@/ui/formatters";

const router = useRouter();
const tickets = ref<CustomerTicket[]>([]);
const status = ref<TicketStatus | "">("");
const category = ref<TicketCategory | "">("");
const loading = ref(false);
const error = ref<ApiError | null>(null);

const statuses: Array<{ value: TicketStatus; label: string }> = [
  { value: "open", label: "待处理" }, { value: "in_progress", label: "处理中" },
  { value: "resolved", label: "已解决" }, { value: "closed", label: "已关闭" },
];
const categories: TicketCategory[] = ["refund_after_sales", "account_security", "product_service", "knowledge_document", "technical_support", "other"];

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    tickets.value = (await ticketApi.list({ status: status.value || undefined, category: category.value || undefined, limit: 100 })).items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "客服工单加载失败。" });
  } finally {
    loading.value = false;
  }
}

watch([status, category], load);
onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader title="客服工单" description="按状态与分类筛选租户内工单，进入处理台后由 AI 辅助分类和生成回复，最终必须人工确认。">
      <button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button>
    </PageHeader>
    <div class="card filter-row">
      <label>状态<select v-model="status"><option value="">全部状态</option><option v-for="item in statuses" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label>分类<select v-model="category"><option value="">全部分类</option><option v-for="item in categories" :key="item" :value="item">{{ ticketCategoryLabel(item) }}</option></select></label>
      <span>共 {{ tickets.length }} 条</span>
    </div>
    <StatusPanel v-if="error" title="加载失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <div class="card">
      <p v-if="loading" class="muted">正在加载…</p>
      <p v-else-if="tickets.length === 0" class="muted">当前筛选条件下暂无工单。</p>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>主题</th><th>状态</th><th>分类</th><th>优先级</th><th>创建时间</th><th></th></tr></thead>
          <tbody>
            <tr v-for="ticket in tickets" :key="ticket.id">
              <td><strong>{{ ticket.subject }}</strong><small>{{ ticket.description }}</small></td>
              <td><span class="tag">{{ ticketStatusLabel(ticket.status) }}</span></td>
              <td>{{ ticketCategoryLabel(ticket.category) }}</td>
              <td>{{ ticketPriorityLabel(ticket.priority) }}</td>
              <td>{{ formatDateTime(ticket.created_at) }}</td>
              <td><button class="secondary-button compact" type="button" @click="router.push(`/service/tickets/${ticket.id}`)">处理</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.filter-row { display: flex; align-items: end; flex-wrap: wrap; gap: 14px; }
.filter-row label { min-width: 180px; }
.filter-row span { margin-left: auto; color: var(--muted); }
.muted { color: var(--muted); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 13px 10px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { color: var(--muted); font-size: 12px; }
td small { display: block; max-width: 420px; margin-top: 6px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.compact { min-height: 34px; padding: 6px 11px; }
</style>

