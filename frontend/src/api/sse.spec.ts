import { vi } from "vitest";

const { apiStreamResponse } = vi.hoisted(() => ({ apiStreamResponse: vi.fn() }));

vi.mock("@/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/client")>();
  return { ...actual, apiStreamResponse };
});

import { streamSse } from "@/api/sse";
import type { SseEvent } from "@/types/api";

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

describe("SSE parser", () => {
  it("parses fragmented CRLF frames and preserves event order", async () => {
    apiStreamResponse.mockResolvedValueOnce(
      streamResponse([
        "event: metadata\r\ndata: {\"run_id\":\"run-1\"}\r\n\r\nevent: tok",
        "en\r\ndata: {\"delta\":\"你\"}\r\n\r\nevent: message_end\r\n",
        "data: {\"message_id\":\"message-1\"}\r\n\r\n",
      ]),
    );
    const events: SseEvent[] = [];
    await streamSse("/ai/chat/stream", { message: "test" }, (event) => events.push(event));
    expect(events.map((event) => event.event)).toEqual(["metadata", "token", "message_end"]);
    expect(events[1]?.data).toEqual({ delta: "你" });
  });

  it("supports multiple data lines in one event", async () => {
    apiStreamResponse.mockResolvedValueOnce(
      streamResponse(["event: token\ndata: {\"delta\":\ndata: \"A\"}\n\n"]),
    );
    const events: SseEvent[] = [];
    await streamSse("/ai/chat/stream", {}, (event) => events.push(event));
    expect(events[0]?.data).toEqual({ delta: "A" });
  });

  it("rejects invalid event JSON", async () => {
    apiStreamResponse.mockResolvedValueOnce(streamResponse(["event: token\ndata: not-json\n\n"]));
    await expect(streamSse("/ai/chat/stream", {}, () => undefined)).rejects.toMatchObject({
      code: "invalid_sse_payload",
    });
  });
});
