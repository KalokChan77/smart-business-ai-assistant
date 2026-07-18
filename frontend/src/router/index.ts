import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import AppShell from "@/layouts/AppShell.vue";
import { defaultPathForRoles } from "@/router/navigation";
import { pinia } from "@/stores";
import { useAuthStore } from "@/stores/auth";
import type { RoleCode } from "@/types/api";

const allRoles: RoleCode[] = ["admin", "decision_maker", "customer_service", "user"];

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true, title: "登录" },
  },
  {
    path: "/403",
    name: "forbidden",
    component: () => import("@/views/ForbiddenView.vue"),
    meta: { title: "无权访问" },
  },
  {
    path: "/",
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      {
        path: "",
        name: "workspace-redirect",
        component: () => import("@/views/WorkspaceRedirectView.vue"),
        meta: { roles: allRoles },
      },
      {
        path: "app/chat",
        name: "app-chat",
        component: () => import("@/views/user/ChatView.vue"),
        meta: { roles: ["user"], title: "AI 对话" },
      },
      {
        path: "app/knowledge",
        name: "app-knowledge",
        component: () => import("@/views/shared/KnowledgeQueryView.vue"),
        meta: { roles: ["user"], title: "知识问答" },
      },
      {
        path: "app/tickets",
        name: "app-tickets",
        component: () => import("@/views/user/MyTicketsView.vue"),
        meta: { roles: ["user"], title: "我的工单" },
      },
      {
        path: "app/conversations",
        name: "app-conversations",
        component: () => import("@/views/user/ConversationsView.vue"),
        meta: { roles: ["user"], title: "历史会话" },
      },
      {
        path: "service/tickets",
        name: "service-tickets",
        component: () => import("@/views/service/ServiceTicketsView.vue"),
        meta: { roles: ["customer_service"], title: "客服工单" },
      },
      {
        path: "service/tickets/:ticketId",
        name: "service-ticket-detail",
        component: () => import("@/views/service/ServiceTicketDetailView.vue"),
        meta: { roles: ["customer_service"], title: "工单处理台" },
      },
      {
        path: "service/knowledge",
        name: "service-knowledge",
        component: () => import("@/views/shared/KnowledgeQueryView.vue"),
        meta: { roles: ["customer_service"], title: "客服知识检索" },
      },
      {
        path: "admin/overview",
        name: "admin-overview",
        component: () => import("@/views/admin/AdminOverviewView.vue"),
        meta: { roles: ["admin"], title: "管理概览" },
      },
      {
        path: "admin/users",
        name: "admin-users",
        component: () => import("@/views/admin/UserManagementView.vue"),
        meta: { roles: ["admin"], title: "用户与角色" },
      },
      {
        path: "admin/knowledge",
        name: "admin-knowledge",
        component: () => import("@/views/admin/KnowledgeDocumentsView.vue"),
        meta: { roles: ["admin"], title: "知识文档" },
      },
      {
        path: "admin/analytics",
        name: "admin-analytics",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: { roles: ["admin"], title: "数据统计", analyticsPanel: "overview" },
      },
      {
        path: "admin/ai-runs",
        name: "admin-ai-runs",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: { roles: ["admin"], title: "AI 质量", analyticsPanel: "ai-runs" },
      },
      {
        path: "decision/overview",
        name: "decision-overview",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: { roles: ["decision_maker"], title: "经营总览", analyticsPanel: "overview" },
      },
      {
        path: "decision/consultations",
        name: "decision-consultations",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: {
          roles: ["decision_maker"],
          title: "咨询趋势",
          analyticsPanel: "consultations",
        },
      },
      {
        path: "decision/categories",
        name: "decision-categories",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: {
          roles: ["decision_maker"],
          title: "问题分类",
          analyticsPanel: "categories",
        },
      },
      {
        path: "decision/satisfaction",
        name: "decision-satisfaction",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: {
          roles: ["decision_maker"],
          title: "满意度",
          analyticsPanel: "satisfaction",
        },
      },
      {
        path: "decision/ai-quality",
        name: "decision-ai-quality",
        component: () => import("@/views/analytics/AnalyticsView.vue"),
        meta: { roles: ["decision_maker"], title: "AI 质量", analyticsPanel: "ai-runs" },
      },
      {
        path: "profile",
        name: "profile",
        component: () => import("@/views/ProfileView.vue"),
        meta: { roles: allRoles, title: "个人中心" },
      },
    ],
  },
  {
    path: "/:pathMatch(.*)*",
    name: "not-found",
    component: () => import("@/views/NotFoundView.vue"),
    meta: { public: true, title: "页面不存在" },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
});

router.beforeEach(async (to) => {
  const auth = useAuthStore(pinia);
  if (!auth.initialized) {
    await auth.restore();
  }

  if (to.meta.public) {
    if (to.name === "login" && auth.user) {
      return defaultPathForRoles(auth.roles, auth.user.id);
    }
    return true;
  }

  if (!auth.user) {
    return { name: "login", query: { redirect: to.fullPath } };
  }

  const roles = (to.meta.roles as RoleCode[] | undefined) ?? [];
  if (roles.length > 0 && !roles.some((role) => auth.roles.includes(role))) {
    return { name: "forbidden" };
  }
  return true;
});

router.afterEach((to) => {
  const title = typeof to.meta.title === "string" ? to.meta.title : "工作台";
  document.title = `${title} · 智慧商务 AI 助手平台`;
});

export default router;
