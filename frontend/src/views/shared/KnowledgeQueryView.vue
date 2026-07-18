<script setup lang="ts">
import { ref } from "vue";

import { ApiError } from "@/api/client";
import { knowledgeApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { KnowledgeAnswer } from "@/types/api";

const query = ref("");
const answer = ref<KnowledgeAnswer | null>(null);
const loading = ref(false);
const error = ref<ApiError | null>(null);

async function submit(): Promise<void> {
  const value = query.value.trim();
  if (!value || loading.value) return;
  loading.value = true;
  error.value = null;
  answer.value = null;
  try {
    answer.value = await knowledgeApi.query(value);
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "知识查询失败。" });
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <section class="content-stack">
    <PageHeader title="知识问答" description="答案只依据当前租户已完成索引的知识文档生成；无匹配或被拒答也是正常业务结果。" />

    <form class="card query-form" @submit.prevent="submit">
      <label>
        输入业务问题
        <textarea v-model="query" maxlength="10000" placeholder="例如：平台退款申请需要准备哪些材料？" />
      </label>
      <div class="button-row">
        <button class="primary-button" type="submit" :disabled="loading || !query.trim()">
          {{ loading ? "正在检索…" : "检索知识库" }}
        </button>
        <button class="secondary-button" type="button" @click="query = ''; answer = null; error = null">清空</button>
      </div>
    </form>

    <StatusPanel v-if="error" title="查询失败" :description="error.message" tone="danger" :request-id="error.requestId" />

    <article v-if="answer" class="card answer-card">
      <div class="answer-heading">
        <h3>查询结果</h3>
        <span class="tag">{{ answer.outcome === 'answered' ? '已回答' : answer.outcome === 'no_match' ? '无匹配' : '已拒答' }}</span>
      </div>
      <p class="answer-text">{{ answer.answer }}</p>
      <p class="muted-copy">召回片段：{{ answer.retrieval_count }} 条</p>
      <div v-if="answer.citations.length" class="citation-list">
        <article v-for="citation in answer.citations" :key="`${citation.rank}-${citation.document_name}`" class="citation-item">
          <strong>{{ citation.rank }}. {{ citation.document_name }}</strong>
          <p>{{ citation.excerpt }}</p>
          <small v-if="citation.score != null && citation.score > 0">相关度：{{ citation.score.toFixed(4) }}</small>
        </article>
      </div>
    </article>
  </section>
</template>

<style scoped>
.query-form { display: grid; gap: 16px; }
.answer-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.answer-heading h3 { margin: 0; }
.answer-text { white-space: pre-wrap; line-height: 1.8; }
.muted-copy { color: var(--muted); }
.citation-list { display: grid; gap: 12px; margin-top: 18px; }
.citation-item { padding: 15px; border: 1px solid var(--line); border-radius: 14px; background: #f8fafc; }
.citation-item p { margin: 8px 0; line-height: 1.65; }
.citation-item small { color: var(--muted); }
</style>
