import type { RoleCode } from "@/types/api";

export interface WorkspaceDefinition {
  role: RoleCode;
  label: string;
  defaultPath: string;
}

export interface NavigationItem {
  label: string;
  to: string;
  roles: RoleCode[];
  section: "workspace" | "account";
  marker: string;
}

export const workspaces: WorkspaceDefinition[] = [
  { role: "admin", label: "管理员工作台", defaultPath: "/admin/overview" },
  {
    role: "decision_maker",
    label: "决策者工作台",
    defaultPath: "/decision/overview",
  },
  {
    role: "customer_service",
    label: "客服工作台",
    defaultPath: "/service/tickets",
  },
  { role: "user", label: "企业用户工作台", defaultPath: "/app/chat" },
];

export const navigationItems: NavigationItem[] = [
  { label: "AI 对话", to: "/app/chat", roles: ["user"], section: "workspace", marker: "AI" },
  {
    label: "知识问答",
    to: "/app/knowledge",
    roles: ["user"],
    section: "workspace",
    marker: "知",
  },
  {
    label: "我的工单",
    to: "/app/tickets",
    roles: ["user"],
    section: "workspace",
    marker: "单",
  },
  {
    label: "历史会话",
    to: "/app/conversations",
    roles: ["user"],
    section: "workspace",
    marker: "史",
  },
  {
    label: "待处理工单",
    to: "/service/tickets",
    roles: ["customer_service"],
    section: "workspace",
    marker: "服",
  },
  {
    label: "客服知识检索",
    to: "/service/knowledge",
    roles: ["customer_service"],
    section: "workspace",
    marker: "知",
  },
  {
    label: "管理概览",
    to: "/admin/overview",
    roles: ["admin"],
    section: "workspace",
    marker: "总",
  },
  {
    label: "用户与角色",
    to: "/admin/users",
    roles: ["admin"],
    section: "workspace",
    marker: "人",
  },
  {
    label: "知识文档",
    to: "/admin/knowledge",
    roles: ["admin"],
    section: "workspace",
    marker: "库",
  },
  {
    label: "数据统计",
    to: "/admin/analytics",
    roles: ["admin"],
    section: "workspace",
    marker: "数",
  },
  {
    label: "AI 质量",
    to: "/admin/ai-runs",
    roles: ["admin"],
    section: "workspace",
    marker: "质",
  },
  {
    label: "经营总览",
    to: "/decision/overview",
    roles: ["decision_maker"],
    section: "workspace",
    marker: "总",
  },
  {
    label: "咨询趋势",
    to: "/decision/consultations",
    roles: ["decision_maker"],
    section: "workspace",
    marker: "趋",
  },
  {
    label: "问题分类",
    to: "/decision/categories",
    roles: ["decision_maker"],
    section: "workspace",
    marker: "类",
  },
  {
    label: "满意度",
    to: "/decision/satisfaction",
    roles: ["decision_maker"],
    section: "workspace",
    marker: "评",
  },
  {
    label: "AI 质量",
    to: "/decision/ai-quality",
    roles: ["decision_maker"],
    section: "workspace",
    marker: "质",
  },
  {
    label: "个人中心",
    to: "/profile",
    roles: ["admin", "decision_maker", "customer_service", "user"],
    section: "account",
    marker: "我",
  },
];

const PREFERENCE_PREFIX = "smart-business-ai.workspace.";

export function availableWorkspaces(roles: RoleCode[]): WorkspaceDefinition[] {
  return workspaces.filter((workspace) => roles.includes(workspace.role));
}

export function defaultPathForRoles(roles: RoleCode[], userId?: string): string {
  if (userId && typeof window !== "undefined") {
    const preferredRole = window.sessionStorage.getItem(`${PREFERENCE_PREFIX}${userId}`);
    const preferred = workspaces.find(
      (workspace) => workspace.role === preferredRole && roles.includes(workspace.role),
    );
    if (preferred) {
      return preferred.defaultPath;
    }
  }
  return availableWorkspaces(roles)[0]?.defaultPath ?? "/403";
}

export function rememberWorkspace(userId: string, role: RoleCode): void {
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(`${PREFERENCE_PREFIX}${userId}`, role);
  }
}

export function navigationForRoles(roles: RoleCode[]): NavigationItem[] {
  return navigationItems.filter((item) => item.roles.some((role) => roles.includes(role)));
}

export function roleForPath(path: string): RoleCode | null {
  if (path.startsWith("/admin/")) return "admin";
  if (path.startsWith("/decision/")) return "decision_maker";
  if (path.startsWith("/service/")) return "customer_service";
  if (path.startsWith("/app/")) return "user";
  return null;
}
