<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import { ApiError } from "@/api/client";
import { analyticsApi } from "@/api/endpoints";
import MetricCard from "@/components/common/MetricCard.vue";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { AIRunMetrics, AnalyticsOverview, CategoryDistribution, ConsultationTrend, SatisfactionMetrics } from "@/types/api";
import { formatPercent, ticketCategoryLabel } from "@/ui/formatters";

type Panel = "overview" | "consultations" | "categories" | "satisfaction" | "ai-runs";

const route = useRoute();
const endDate = ref(new Date().toISOString().slice(0, 10));
const startDate = ref(new Date(Date.now() - 29 * 86400000).toISOString().slice(0, 10));
const overview = ref<AnalyticsOverview | null>(null);
const consultations = ref<ConsultationTrend | null>(null);
const categories = ref<CategoryDistribution | null>(null);
const satisfaction = ref<SatisfactionMetrics | null>(null);
const aiRuns = ref<AIRunMetrics | null>(null);
const loading = ref(false);
const error = ref<ApiError | null>(null);
const panel = computed<Panel>(() => route.meta.analyticsPanel || "overview");
const title = computed(() => ({ overview: "经营与服务总览", consultations: "咨询趋势", categories: "问题分类", satisfaction: "用户满意度", "ai-runs": "AI 运行质量" })[panel.value]);
const maxConsultations = computed(() => Math.max(1, ...(consultations.value?.points.map((item) => item.consultation_count) || [1])));

async function load(): Promise<void> {
  loading.value = true; error.value = null;
  try {
    if (panel.value === "overview") overview.value = await analyticsApi.overview(startDate.value, endDate.value);
    else if (panel.value === "consultations") consultations.value = await analyticsApi.consultations(startDate.value, endDate.value);
    else if (panel.value === "categories") categories.value = await analyticsApi.categories(startDate.value, endDate.value);
    else if (panel.value === "satisfaction") satisfaction.value = await analyticsApi.satisfaction(startDate.value, endDate.value);
    else aiRuns.value = await analyticsApi.aiRuns(startDate.value, endDate.value);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "统计数据加载失败。" });
  } finally { loading.value = false; }
}

watch(() => route.fullPath, load);
onMounted(load);
</script>

<template>
  <section class="content-stack">
    <PageHeader :title="title" description="统计按当前租户和 UTC 日期边界实时聚合；百分比字段由后端直接返回 0–100。">
      <button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button>
    </PageHeader>
    <form class="card date-filter" @submit.prevent="load">
      <label>开始日期<input v-model="startDate" type="date" /></label><label>结束日期<input v-model="endDate" type="date" /></label>
      <button class="primary-button" type="submit" :disabled="loading || !startDate || !endDate || startDate > endDate">{{ loading ? "统计中…" : "应用日期" }}</button>
    </form>
    <StatusPanel v-if="error" title="统计加载失败" :description="error.message" tone="danger" :request-id="error.requestId" />

    <template v-if="panel === 'overview' && overview">
      <div class="metric-grid">
        <MetricCard label="咨询量" :value="overview.consultation_count" :hint="`${overview.resolved_consultation_count} 条已解决`" />
        <MetricCard label="解决率" :value="formatPercent(overview.resolution_rate)" hint="已解决 / 咨询总量" tone="green" />
        <MetricCard label="人工接管率" :value="formatPercent(overview.human_takeover_rate)" :hint="`${overview.human_takeover_count} 次人工接管`" tone="amber" />
        <MetricCard label="满意度" :value="formatPercent(overview.satisfaction_rate)" :hint="`${overview.feedback_count} 条反馈`" tone="violet" />
      </div>
      <div class="overview-grid">
        <article class="card"><h3>AI 运行</h3><dl><div><dt>运行总量</dt><dd>{{ overview.ai_run_count }}</dd></div><div><dt>终态运行</dt><dd>{{ overview.ai_terminal_run_count }}</dd></div><div><dt>成功率</dt><dd>{{ formatPercent(overview.ai_success_rate) }}</dd></div></dl></article>
        <article class="card"><h3>高频问题</h3><p v-if="overview.top_questions.length === 0" class="muted">当前周期暂无问题。</p><ol v-else><li v-for="item in overview.top_questions" :key="item.question"><span>{{ item.question }}</span><strong>{{ item.count }}</strong></li></ol></article>
      </div>
    </template>

    <article v-if="panel === 'consultations' && consultations" class="card">
      <h3>每日咨询趋势</h3><p v-if="consultations.points.length === 0" class="muted">当前周期暂无数据。</p>
      <div v-else class="trend-chart">
        <div v-for="point in consultations.points" :key="point.date" class="trend-row"><span>{{ point.date }}</span><div class="bar-track"><i :style="{ width: `${(point.consultation_count / maxConsultations) * 100}%` }" /></div><strong>{{ point.consultation_count }}</strong><small>解决 {{ point.resolved_count }} / 接管 {{ point.human_takeover_count }}</small></div>
      </div>
    </article>

    <article v-if="panel === 'categories' && categories" class="card">
      <h3>问题分类分布（共 {{ categories.total }} 条）</h3><p v-if="categories.items.length === 0" class="muted">当前周期暂无分类数据。</p>
      <div v-else class="category-list"><div v-for="item in categories.items" :key="item.category"><span>{{ ticketCategoryLabel(item.category) }}</span><div class="bar-track"><i :style="{ width: `${item.percentage}%` }" /></div><strong>{{ item.count }}</strong><small>{{ formatPercent(item.percentage) }}</small></div></div>
    </article>

    <template v-if="panel === 'satisfaction' && satisfaction">
      <div class="metric-grid"><MetricCard label="反馈总量" :value="satisfaction.feedback_count" /><MetricCard label="正向反馈" :value="satisfaction.positive_count" tone="green" /><MetricCard label="负向反馈" :value="satisfaction.negative_count" tone="amber" /><MetricCard label="满意度" :value="formatPercent(satisfaction.satisfaction_rate)" tone="violet" /></div>
      <article class="card gauge-card"><div class="gauge"><span :style="{ width: `${satisfaction.satisfaction_rate}%` }" /></div><strong>{{ formatPercent(satisfaction.satisfaction_rate) }}</strong><p>无反馈时后端返回完整零值结构，不将其误判为接口异常。</p></article>
    </template>

    <template v-if="panel === 'ai-runs' && aiRuns">
      <div class="metric-grid"><MetricCard label="运行总量" :value="aiRuns.total" /><MetricCard label="成功" :value="aiRuns.succeeded" tone="green" /><MetricCard label="失败 / 取消" :value="`${aiRuns.failed} / ${aiRuns.cancelled}`" tone="amber" /><MetricCard label="成功率" :value="formatPercent(aiRuns.success_rate)" tone="violet" /></div>
      <div class="overview-grid">
        <article class="card"><h3>资源消耗</h3><dl><div><dt>平均耗时</dt><dd>{{ aiRuns.average_duration_ms.toFixed(0) }} ms</dd></div><div><dt>平均输入 Token</dt><dd>{{ aiRuns.average_input_tokens.toFixed(1) }}</dd></div><div><dt>平均输出 Token</dt><dd>{{ aiRuns.average_output_tokens.toFixed(1) }}</dd></div><div><dt>运行中</dt><dd>{{ aiRuns.running }}</dd></div></dl></article>
        <article class="card"><h3>错误分布</h3><p v-if="aiRuns.errors.length === 0" class="muted">当前周期无失败错误。</p><ol v-else><li v-for="item in aiRuns.errors" :key="item.code"><code>{{ item.code }}</code><strong>{{ item.count }}</strong></li></ol></article>
      </div>
      <article class="card"><h3>模型维度</h3><div class="table-wrap"><table><thead><tr><th>提供商 / 模型</th><th>运行</th><th>成功</th><th>失败</th><th>成功率</th><th>平均耗时</th></tr></thead><tbody><tr v-for="item in aiRuns.by_model" :key="`${item.provider}-${item.model}`"><td><strong>{{ item.provider }}</strong><small>{{ item.model }}</small></td><td>{{ item.total }}</td><td>{{ item.succeeded }}</td><td>{{ item.failed }}</td><td>{{ formatPercent(item.success_rate) }}</td><td>{{ item.average_duration_ms.toFixed(0) }} ms</td></tr></tbody></table></div></article>
    </template>

    <StatusPanel v-if="!loading && !error && ((panel === 'overview' && !overview) || (panel === 'consultations' && !consultations) || (panel === 'categories' && !categories) || (panel === 'satisfaction' && !satisfaction) || (panel === 'ai-runs' && !aiRuns))" title="暂无统计结果" description="请调整日期范围后重试。" />
  </section>
</template>

<style scoped>
.date-filter { display: flex; align-items: end; flex-wrap: wrap; gap: 13px; }
.date-filter label { min-width: 180px; }
.overview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.card h3 { margin-top: 0; }
dl { display: grid; gap: 0; margin: 0; } dl div { display: flex; justify-content: space-between; padding: 12px 0; border-bottom: 1px solid var(--line); } dt { color: var(--muted); } dd { margin: 0; font-weight: 800; }
ol { display: grid; gap: 9px; padding-left: 22px; } li { padding-left: 5px; } ol li span { display: inline-block; max-width: 78%; } ol li strong { float: right; }
.muted { color: var(--muted); }
.trend-chart, .category-list { display: grid; gap: 11px; margin-top: 18px; }
.trend-row { display: grid; grid-template-columns: 100px minmax(120px, 1fr) 44px minmax(140px, auto); align-items: center; gap: 10px; }
.trend-row small { color: var(--muted); }
.bar-track { height: 13px; overflow: hidden; border-radius: 999px; background: #e8eef8; }
.bar-track i { display: block; min-width: 2px; height: 100%; border-radius: inherit; background: linear-gradient(90deg, #2563eb, #7c3aed); }
.category-list > div { display: grid; grid-template-columns: 140px 1fr 50px 70px; align-items: center; gap: 10px; }
.category-list small { color: var(--muted); text-align: right; }
.gauge-card { text-align: center; }.gauge { height: 22px; overflow: hidden; border-radius: 999px; background: #e8eef8; }.gauge span { display: block; height: 100%; background: linear-gradient(90deg, #10b981, #2563eb); }.gauge-card > strong { display: block; margin: 18px 0 6px; font-size: 34px; }.gauge-card p { color: var(--muted); }
.table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; } th, td { padding: 12px 10px; border-bottom: 1px solid var(--line); text-align: left; } th { color: var(--muted); font-size: 12px; } td small { display: block; margin-top: 4px; color: var(--muted); }
@media (max-width: 850px) { .overview-grid { grid-template-columns: 1fr; } .trend-row { grid-template-columns: 86px 1fr 35px; } .trend-row small { grid-column: 2 / -1; } .category-list > div { grid-template-columns: 110px 1fr 36px; } .category-list small { grid-column: 2 / -1; } }
</style>
