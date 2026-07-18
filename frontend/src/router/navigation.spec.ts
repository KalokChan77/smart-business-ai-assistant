import {
  defaultPathForRoles,
  navigationForRoles,
  rememberWorkspace,
  roleForPath,
} from "@/router/navigation";

describe("role navigation", () => {
  it.each([
    [["admin"] as const, "/admin/overview"],
    [["decision_maker"] as const, "/decision/overview"],
    [["customer_service"] as const, "/service/tickets"],
    [["user"] as const, "/app/chat"],
  ])("routes %s to its workspace", (roles, expected) => {
    expect(defaultPathForRoles([...roles])).toBe(expected);
  });

  it("restores an authorized workspace preference for a multi-role user", () => {
    rememberWorkspace("user-1", "user");
    expect(defaultPathForRoles(["admin", "user"], "user-1")).toBe("/app/chat");
  });

  it("does not restore a workspace the user no longer owns", () => {
    rememberWorkspace("user-2", "admin");
    expect(defaultPathForRoles(["user"], "user-2")).toBe("/app/chat");
  });

  it("only exposes navigation items authorized by roles", () => {
    const items = navigationForRoles(["customer_service"]);
    expect(items.map((item) => item.to)).toEqual([
      "/service/tickets",
      "/service/knowledge",
      "/profile",
    ]);
    expect(items.some((item) => item.to.startsWith("/admin/"))).toBe(false);
  });

  it("maps workspace paths back to role boundaries", () => {
    expect(roleForPath("/admin/users")).toBe("admin");
    expect(roleForPath("/decision/categories")).toBe("decision_maker");
    expect(roleForPath("/service/tickets/1")).toBe("customer_service");
    expect(roleForPath("/app/chat")).toBe("user");
    expect(roleForPath("/profile")).toBeNull();
  });
});

