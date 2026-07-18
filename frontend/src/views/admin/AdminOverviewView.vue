<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError } from "@/api/client";
import { analyticsApi, knowledgeApi, usersApi } from "@/api/endpoints";
import MetricCard from "@/components/common/MetricCard.vue";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { AnalyticsOverview, KnowledgeDocument, UserAccount } from "@/types/api";
import { formatPercent } from "@/ui/formatters";

const overview = ref<AnalyticsOverview | null>(null);
const users = ref<UserAccount[]>([]);
const documents = ref<KnowledgeDocument[]>([]);
const loading = ref(false);
const error = ref<ApiError | null>(null);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const [analytics, userList, documentPage] = await Promise.all([
      analyticsApi.overview(), usersApi.list(), knowledgeApi.listDocuments(100),
    ]);
    overview.value = analytics;
    users.value = userList;
    documents.value = documentPage.items;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "管理概览加载失败。" });
  } finally { loading.value = false; }
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader title="管理概览" description="集中查看租户用户、知识库索引与 AI 运行的基础状态。">
      <button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button>
    </PageHeader>
    <StatusPanel v-if="error" title="加载失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <div class="metric-grid">
      <MetricCard label="租户用户" :value="users.length" hint="含启用与停用账号" />
      <MetricCard label="知识文档" :value="documents.length" :hint="`${documents.filter((item) => item.status === 'completed').length} 份已完成索引`" tone="green" />
      <MetricCard label="咨询总量" :value="overview?.consultation_count ?? '—'" hint="当前统计周期" tone="violet" />
      <MetricCard label="AI 成功率" :value="overview ? formatPercent(overview.ai_success_rate) : '—'" hint="只基于终态运行" tone="amber" />
    </div>
    <div class="management-grid">
      <RouterLink class="card management-card" to="/admin/users"><span>用户与角色</span><strong>创建账号、分配角色、停用账号</strong><small>进入管理 →</small></RouterLink>
      <RouterLink class="card management-card" to="/admin/knowledge"><span>知识文档</span><strong>上传 PDF/Word、重建索引、查看任务</strong><small>进入管理 →</small></RouterLink>
      <RouterLink class="card management-card" to="/admin/analytics"><span>数据统计</span><strong>咨询、分类、满意度与 AI 质量</strong><small>查看统计 →</small></RouterLink>
    </div>
    <StatusPanel v-if="!loading && documents.some((item) => item.status === 'failed')" title="存在索引失败文档" description="请前往知识文档页面查看稳定错误码并重新索引。" tone="warning" />
  </section>
</template>

<style scoped>
.management-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.management-card { display: grid; gap: 10px; transition: transform 160ms ease, border-color 160ms ease; }
.management-card:hover { transform: translateY(-2px); border-color: #a8bfff; }
.management-card span, .management-card small { color: var(--muted); }
.management-card strong { line-height: 1.55; }
.management-card small { color: var(--blue); font-weight: 700; }
@media (max-width: 900px) { .management-grid { grid-template-columns: 1fr; } }
</style>

