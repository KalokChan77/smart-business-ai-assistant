<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";

import { ApiError } from "@/api/client";
import { aiApi, conversationApi } from "@/api/endpoints";
import { streamSse } from "@/api/sse";
import PageHeader from "@/components/common/PageHeader.vue";
import StatusPanel from "@/components/common/StatusPanel.vue";

type ChatMode = "chat" | "agent";
type Provider = "default" | "deepseek" | "dashscope";

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  completed?: boolean;
  runId?: string;
  feedback?: "positive" | "negative";
}

interface ToolTrace {
  tool: string;
  status: "running" | "completed";
  output?: string;
}

const input = ref("");
const mode = ref<ChatMode>("chat");
const provider = ref<Provider>("default");
const conversationId = ref<string | null>(null);
const messages = ref<DisplayMessage[]>([]);
const tools = ref<ToolTrace[]>([]);
const sending = ref(false);
const error = ref<ApiError | null>(null);
const statusText = ref("尚未开始对话");
let controller: AbortController | null = null;

function dataString(data: Record<string, unknown>, key: string): string {
  const value = data[key];
  return typeof value === "string" ? value : "";
}

async function ensureConversation(prompt: string): Promise<string> {
  if (conversationId.value) return conversationId.value;
  const conversation = await conversationApi.create(prompt.slice(0, 40));
  conversationId.value = conversation.id;
  return conversation.id;
}

async function send(): Promise<void> {
  const prompt = input.value.trim();
  if (!prompt || sending.value) return;
  input.value = "";
  sending.value = true;
  error.value = null;
  tools.value = [];
  statusText.value = "准备 AI 运行…";

  const userMessage: DisplayMessage = { id: crypto.randomUUID(), role: "user", content: prompt, completed: true };
  const assistantMessage: DisplayMessage = { id: crypto.randomUUID(), role: "assistant", content: "", pending: true, completed: false };
  messages.value.push(userMessage, assistantMessage);

  try {
    const id = await ensureConversation(prompt);
    controller = new AbortController();
    let streamError: { code: string; message: string; requestId?: string } | null = null;
    const payload: Record<string, string> = { conversation_id: id, message: prompt };
    if (provider.value !== "default") payload.provider = provider.value;

    await streamSse(
      mode.value === "agent" ? "/ai/agent/stream" : "/ai/chat/stream",
      payload,
      ({ event, data }) => {
        if (event === "metadata") {
          assistantMessage.runId = dataString(data, "run_id");
          statusText.value = `正在调用 ${dataString(data, "provider") || "默认"} 模型…`;
        } else if (event === "token") {
          assistantMessage.content += dataString(data, "delta");
        } else if (event === "tool_start") {
          tools.value.push({ tool: dataString(data, "tool") || "未知工具", status: "running" });
          statusText.value = `Agent 正在调用 ${dataString(data, "tool") || "工具"}…`;
        } else if (event === "tool_end") {
          const tool = dataString(data, "tool");
          const trace = [...tools.value].reverse().find((item) => item.tool === tool && item.status === "running");
          if (trace) {
            trace.status = "completed";
            trace.output = dataString(data, "output");
          }
          statusText.value = "工具调用完成，正在组织回答…";
        } else if (event === "message_end") {
          assistantMessage.runId = dataString(data, "run_id") || assistantMessage.runId;
          assistantMessage.pending = false;
          assistantMessage.completed = true;
          statusText.value = "回答已完成并持久化";
        } else if (event === "error") {
          streamError = {
            code: dataString(data, "code") || "ai_stream_failed",
            message: dataString(data, "message") || "AI 流式回答失败。",
            requestId: dataString(data, "request_id") || undefined,
          };
        }
      },
      controller.signal,
    );

    if (streamError) {
      const failure = streamError as { code: string; message: string; requestId?: string };
      throw new ApiError({ status: 0, code: failure.code, message: failure.message, requestId: failure.requestId });
    }
    if (!assistantMessage.completed) {
      throw new ApiError({ status: 0, code: "sse_incomplete", message: "流式连接提前结束，回答未确认保存。" });
    }
  } catch (caught) {
    assistantMessage.pending = false;
    assistantMessage.completed = false;
    if (!assistantMessage.content) assistantMessage.content = "本次回答未完成，请稍后重试。";
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "AI 对话失败。" });
    statusText.value = "本次运行失败";
  } finally {
    controller = null;
    sending.value = false;
  }
}

function stop(): void {
  controller?.abort();
}

async function submitFeedback(message: DisplayMessage, rating: "positive" | "negative"): Promise<void> {
  if (!message.completed || !message.runId) return;
  error.value = null;
  try {
    await aiApi.feedback(message.runId, rating);
    message.feedback = rating;
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "评价提交失败。" });
  }
}

async function play(message: DisplayMessage): Promise<void> {
  if (!message.completed || !message.content) return;
  error.value = null;
  try {
    const blob = await aiApi.tts(message.content);
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
    audio.addEventListener("error", () => URL.revokeObjectURL(url), { once: true });
    await audio.play();
  } catch (caught) {
    error.value = caught instanceof ApiError ? caught : new ApiError({ status: 0, code: "unknown", message: "语音播放失败。" });
  }
}

async function newConversation(): Promise<void> {
  stop();
  conversationId.value = null;
  messages.value = [];
  tools.value = [];
  error.value = null;
  statusText.value = "已开始新会话";
}

onBeforeUnmount(stop);
</script>

<template>
  <section class="chat-page">
    <PageHeader title="AI 对话" description="通过 FastAPI 统一编排 DeepSeek、百炼与 LangGraph；浏览器不接触任何模型密钥。">
      <button class="secondary-button" type="button" @click="newConversation">新会话</button>
    </PageHeader>

    <StatusPanel v-if="error" title="对话异常" :description="error.message" tone="danger" :request-id="error.requestId" />

    <div class="chat-layout">
      <main class="card chat-main">
        <div v-if="messages.length === 0" class="chat-empty">
          <strong>开始一次模拟业务咨询</strong>
          <p>可以询问平台能力、售后政策，或切换 Agent 模式完成安全计算与演示政策查询。</p>
        </div>
        <div v-else class="chat-messages">
          <article v-for="message in messages" :key="message.id" :class="['chat-message', message.role]">
            <strong>{{ message.role === 'user' ? '我' : 'AI 助手' }}</strong>
            <p>{{ message.content }}<span v-if="message.pending" class="cursor">▍</span></p>
            <div v-if="message.role === 'assistant' && message.completed" class="message-actions">
              <button type="button" :class="{ selected: message.feedback === 'positive' }" @click="submitFeedback(message, 'positive')">有帮助</button>
              <button type="button" :class="{ selected: message.feedback === 'negative' }" @click="submitFeedback(message, 'negative')">需改进</button>
              <button type="button" @click="play(message)">朗读</button>
            </div>
          </article>
        </div>

        <form class="composer" @submit.prevent="send">
          <textarea v-model="input" maxlength="100000" placeholder="输入消息，Ctrl/Command + Enter 也可发送" @keydown.meta.enter.prevent="send" @keydown.ctrl.enter.prevent="send" />
          <div class="composer-footer">
            <div class="composer-options">
              <select v-model="mode" :disabled="sending"><option value="chat">普通对话</option><option value="agent">LangGraph Agent</option></select>
              <select v-model="provider" :disabled="sending"><option value="default">服务端默认模型</option><option value="deepseek">DeepSeek</option><option value="dashscope">阿里云百炼</option></select>
            </div>
            <button v-if="sending" class="danger-button" type="button" @click="stop">停止</button>
            <button v-else class="primary-button" type="submit" :disabled="!input.trim()">发送</button>
          </div>
        </form>
      </main>

      <aside class="card run-panel">
        <h3>运行状态</h3>
        <p>{{ statusText }}</p>
        <small>会话 ID：{{ conversationId || '新会话尚未创建' }}</small>
        <div v-if="tools.length" class="tool-list">
          <article v-for="(tool, index) in tools" :key="`${tool.tool}-${index}`">
            <strong>{{ tool.tool }}</strong>
            <span>{{ tool.status === 'running' ? '执行中' : '已完成' }}</span>
            <code v-if="tool.output">{{ tool.output }}</code>
          </article>
        </div>
        <p class="security-copy">仅在收到 <code>message_end</code> 后，页面才将回答标记为已完成并开放反馈与语音功能。</p>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.chat-page { display: grid; gap: 20px; }
.chat-layout { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 18px; }
.chat-main { display: grid; min-height: 650px; grid-template-rows: 1fr auto; gap: 18px; }
.chat-empty { align-self: center; text-align: center; color: var(--muted); }
.chat-empty strong { color: #1d2939; font-size: 20px; }
.chat-empty p { max-width: 580px; margin: 12px auto; line-height: 1.7; }
.chat-messages { display: grid; align-content: start; gap: 15px; max-height: 560px; overflow-y: auto; }
.chat-message { width: min(82%, 760px); padding: 15px 17px; border-radius: 16px; background: #f1f5f9; }
.chat-message.user { justify-self: end; background: var(--blue-soft); }
.chat-message p { margin: 8px 0 0; white-space: pre-wrap; line-height: 1.72; }
.cursor { color: var(--blue); animation: blink .8s infinite; }
.message-actions { display: flex; gap: 8px; margin-top: 12px; }
.message-actions button { padding: 5px 9px; border: 1px solid var(--line); border-radius: 8px; background: white; cursor: pointer; }
.message-actions button.selected { color: white; border-color: var(--blue); background: var(--blue); }
.composer { display: grid; gap: 10px; padding-top: 16px; border-top: 1px solid var(--line); }
.composer textarea { min-height: 100px; }
.composer-footer { display: flex; justify-content: space-between; gap: 12px; }
.composer-options { display: flex; flex-wrap: wrap; gap: 8px; }
.composer-options select { min-height: 40px; }
.run-panel { align-self: start; }
.run-panel h3 { margin-top: 0; }
.run-panel > p, .run-panel > small { color: var(--muted); overflow-wrap: anywhere; }
.tool-list { display: grid; gap: 10px; margin: 18px 0; }
.tool-list article { display: grid; gap: 5px; padding: 11px; border: 1px solid var(--line); border-radius: 12px; }
.tool-list span { color: var(--green); font-size: 12px; }
.tool-list code { max-height: 120px; overflow: auto; font-size: 11px; }
.security-copy { padding-top: 15px; border-top: 1px solid var(--line); font-size: 12px; line-height: 1.65; }
@keyframes blink { 50% { opacity: 0; } }
@media (max-width: 980px) { .chat-layout { grid-template-columns: 1fr; } .run-panel { order: -1; } }
@media (max-width: 600px) { .composer-footer { align-items: stretch; flex-direction: column; } .composer-options { display: grid; } .chat-message { width: 94%; } }
</style>
