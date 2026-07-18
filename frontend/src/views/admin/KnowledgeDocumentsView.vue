<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError } from "@/api/client";
import { knowledgeApi } from "@/api/endpoints";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";
import type { KnowledgeDocument, KnowledgeJob } from "@/types/api";
import { formatBytes, formatDateTime } from "@/ui/formatters";

const documents = ref<KnowledgeDocument[]>([]);
const jobs = ref<Record<string, KnowledgeJob>>({});
const file = ref<File | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const loading = ref(false);
const actionId = ref<string | null>(null);
const error = ref<ApiError | null>(null);
const success = ref("");
let timer: number | null = null;

async function load(): Promise<void> {
  loading.value = true; error.value = null;
  try { documents.value = (await knowledgeApi.listDocuments(100)).items; }
  catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "知识文档加载失败。" }); }
  finally { loading.value = false; }
}

function track(job: KnowledgeJob): void { jobs.value = { ...jobs.value, [job.document_id]: job }; }

async function pollJobs(): Promise<void> {
  const active = Object.values(jobs.value).filter((job) => job.status === "pending" || job.status === "processing");
  if (active.length === 0) return;
  await Promise.all(active.map(async (job) => {
    try { track(await knowledgeApi.job(job.id)); } catch { /* 下一轮或手动刷新重试，不覆盖页面主错误。 */ }
  }));
  if (Object.values(jobs.value).some((job) => job.status === "completed" || job.status === "failed")) await load();
}

function chooseFile(event: Event): void { file.value = (event.target as HTMLInputElement).files?.[0] || null; }

async function upload(): Promise<void> {
  if (!file.value) return;
  actionId.value = "upload"; error.value = null; success.value = "";
  try {
    const result = await knowledgeApi.upload(file.value);
    track(result.job); success.value = "文档已上传，后台正在建立索引。";
    file.value = null; if (fileInput.value) fileInput.value.value = "";
    await load();
  } catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "文档上传失败。" }); }
  finally { actionId.value = null; }
}

async function reindex(document: KnowledgeDocument): Promise<void> {
  actionId.value = document.id; error.value = null; success.value = "";
  try { const result = await knowledgeApi.reindex(document.id); track(result.job); success.value = "重建索引任务已创建。"; await load(); }
  catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "重建索引失败。" }); }
  finally { actionId.value = null; }
}

async function remove(document: KnowledgeDocument): Promise<void> {
  if (!window.confirm(`确认删除“${document.filename}”吗？`)) return;
  actionId.value = document.id; error.value = null; success.value = "";
  try { const result = await knowledgeApi.remove(document.id); track(result.job); success.value = "删除任务已创建。"; await load(); }
  catch (caught) { error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "文档删除失败。" }); }
  finally { actionId.value = null; }
}

onMounted(async () => { await load(); timer = window.setInterval(pollJobs, 2500); });
onBeforeUnmount(() => { if (timer !== null) window.clearInterval(timer); });
</script>

<template>
  <section class="content-stack">
    <PageHeader title="知识文档" description="上传 PDF 或 Word 后由后台异步解析、切分和索引；页面仅轮询公开任务状态。"><button class="secondary-button" type="button" :disabled="loading" @click="load">刷新</button></PageHeader>
    <StatusPanel v-if="error" title="操作失败" :description="error.message" tone="danger" :request-id="error.requestId" />
    <StatusPanel v-if="success" title="操作已提交" :description="success" tone="success" />
    <form class="card upload-row" @submit.prevent="upload">
      <label>选择文档<input ref="fileInput" type="file" accept=".pdf,.doc,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" @change="chooseFile" /></label>
      <span>{{ file ? `${file.name} · ${formatBytes(file.size)}` : '尚未选择文件' }}</span>
      <button class="primary-button" type="submit" :disabled="!file || actionId !== null">{{ actionId === 'upload' ? '上传中…' : '上传并索引' }}</button>
    </form>
    <div class="card">
      <p v-if="loading" class="muted">正在加载…</p><p v-else-if="documents.length === 0" class="muted">暂无知识文档。</p>
      <div v-else class="document-list">
        <article v-for="document in documents" :key="document.id" class="document-row">
          <div><strong>{{ document.filename }}</strong><p>{{ document.media_type }} · {{ formatBytes(document.size_bytes) }}</p><small>{{ formatDateTime(document.created_at) }}</small></div>
          <div class="status-cell"><span class="tag">{{ document.status }}</span><small>{{ document.indexing_status || '—' }}</small><code v-if="document.latest_error_code">{{ document.latest_error_code }}</code></div>
          <div v-if="jobs[document.id]" class="job-cell"><strong>{{ jobs[document.id].operation }} · {{ jobs[document.id].status }}</strong><span v-if="jobs[document.id].total_segments">{{ jobs[document.id].completed_segments || 0 }}/{{ jobs[document.id].total_segments }} 分段</span><code v-if="jobs[document.id].error_code">{{ jobs[document.id].error_code }}</code></div>
          <div class="button-row"><button class="secondary-button compact" type="button" :disabled="actionId !== null || document.status === 'deleted'" @click="reindex(document)">重建索引</button><button class="danger-button compact" type="button" :disabled="actionId !== null || document.status === 'deleted'" @click="remove(document)">删除</button></div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.upload-row { display: grid; grid-template-columns: minmax(280px, 1fr) auto auto; align-items: end; gap: 14px; }
.upload-row > span, .muted { color: var(--muted); }
.document-list { display: grid; gap: 12px; }
.document-row { display: grid; grid-template-columns: minmax(220px, 1.2fr) minmax(150px, .6fr) minmax(170px, .7fr) auto; align-items: center; gap: 14px; padding: 15px; border: 1px solid var(--line); border-radius: 13px; }
.document-row p { margin: 6px 0; color: #475467; }
.document-row small { color: var(--muted); }
.status-cell, .job-cell { display: grid; justify-items: start; gap: 6px; }
.status-cell code, .job-cell code { color: var(--red); font-size: 11px; }
.compact { min-height: 34px; padding: 6px 10px; }
@media (max-width: 1050px) { .document-row { grid-template-columns: 1fr 1fr; } }
@media (max-width: 720px) { .upload-row, .document-row { grid-template-columns: 1fr; } }
</style>
