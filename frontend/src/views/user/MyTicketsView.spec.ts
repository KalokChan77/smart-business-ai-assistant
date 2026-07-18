import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { list, create, get } = vi.hoisted(() => ({
  list: vi.fn(),
  create: vi.fn(),
  get: vi.fn(),
}));

vi.mock("@/api/endpoints", () => ({
  ticketApi: { list, create, get },
}));

import MyTicketsView from "@/views/user/MyTicketsView.vue";

const ticket = {
  id: "ticket-1",
  subject: "退款申请材料咨询",
  description: "请客服协助确认退款材料。",
  status: "resolved" as const,
  category: "refund_after_sales" as const,
  priority: "high" as const,
  resolved_at: "2026-07-18T01:00:00Z",
  created_at: "2026-07-18T00:00:00Z",
  updated_at: "2026-07-18T01:00:00Z",
};

describe("MyTicketsView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    list.mockResolvedValue({ items: [ticket], total: 1, limit: 100, offset: 0 });
    get.mockResolvedValue({
      view: "public",
      ticket,
      confirmed_reply: {
        final_reply: "退款材料已由客服人工核对。",
        confirmed_at: "2026-07-18T01:00:00Z",
      },
    });
  });

  it("loads and displays the confirmed customer-service reply on demand", async () => {
    const wrapper = mount(MyTicketsView);
    await flushPromises();

    expect(wrapper.text()).toContain("退款申请材料咨询");
    expect(wrapper.text()).not.toContain("退款材料已由客服人工核对。");

    await wrapper.get(".ticket-meta button").trigger("click");
    await flushPromises();

    expect(get).toHaveBeenCalledWith("ticket-1");
    expect(wrapper.text()).toContain("客服最终回复");
    expect(wrapper.text()).toContain("退款材料已由客服人工核对。");
  });
});
