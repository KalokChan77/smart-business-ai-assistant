import { apiStreamResponse, ApiError } from "@/api/client";
import type { SseEvent, SseEventName } from "@/types/api";

const supportedEvents = new Set<SseEventName>([
  "metadata",
  "token",
  "tool_start",
  "tool_end",
  "message_end",
  "error",
]);

export async function streamSse(
  path: string,
  body: unknown,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await apiStreamResponse(path, {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
  if (!response.body) {
    throw new ApiError({
      status: 0,
      code: "sse_stream_missing",
      message: "浏览器没有收到可读取的流式响应。",
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      emitBlock(block, onEvent);
    }
    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    emitBlock(buffer, onEvent);
  }
}

function emitBlock(block: string, onEvent: (event: SseEvent) => void): void {
  let name = "message";
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      name = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!supportedEvents.has(name as SseEventName) || dataLines.length === 0) {
    return;
  }
  try {
    onEvent({
      event: name as SseEventName,
      data: JSON.parse(dataLines.join("\n")) as Record<string, unknown>,
    });
  } catch {
    throw new ApiError({
      status: 0,
      code: "invalid_sse_payload",
      message: "流式响应格式无法解析。",
    });
  }
}
