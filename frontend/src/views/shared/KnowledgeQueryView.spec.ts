import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { queryKnowledge } = vi.hoisted(() => ({
  queryKnowledge: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  knowledgeApi: { query: queryKnowledge },
}));

import KnowledgeQueryView from "@/views/shared/KnowledgeQueryView.vue";

function answerWithScore(score: number | null) {
  return {
    outcome: "answered" as const,
    answer: "根据当前知识库，找到退款说明。",
    retrieval_count: 1,
    citations: [
      {
        rank: 1,
        document_name: "退款规则.md",
        excerpt: "支付后 7 个自然日内可申请。",
        score,
      },
    ],
  };
}

async function submitQuery(wrapper: ReturnType<typeof mount>): Promise<void> {
  await wrapper.get("textarea").setValue("退款条件是什么？");
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

describe("KnowledgeQueryView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("hides a missing keyword relevance score", async () => {
    queryKnowledge.mockResolvedValue(answerWithScore(null));
    const wrapper = mount(KnowledgeQueryView);

    await submitQuery(wrapper);

    expect(wrapper.text()).toContain("退款规则.md");
    expect(wrapper.text()).not.toContain("相关度：");
    expect(wrapper.text()).not.toContain("0.0000");
  });

  it("labels a positive upstream score as relevance", async () => {
    queryKnowledge.mockResolvedValue(answerWithScore(0.875));
    const wrapper = mount(KnowledgeQueryView);

    await submitQuery(wrapper);

    expect(wrapper.text()).toContain("相关度：0.8750");
    expect(wrapper.text()).not.toContain("相似度");
  });
});
