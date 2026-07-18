import type { TicketCategory, TicketPriority, TicketStatus } from "@/types/api";

const categoryLabels: Record<TicketCategory | "unclassified", string> = {
  refund_after_sales: "退款与售后",
  account_security: "账号安全",
  product_service: "产品与服务",
  knowledge_document: "知识文档",
  technical_support: "技术支持",
  other: "其他",
  unclassified: "未分类",
};

const statusLabels: Record<TicketStatus, string> = {
  open: "待处理",
  in_progress: "处理中",
  resolved: "已解决",
  closed: "已关闭",
};

const priorityLabels: Record<TicketPriority, string> = {
  low: "低",
  normal: "普通",
  high: "高",
  urgent: "紧急",
};

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

export function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function ticketCategoryLabel(value: TicketCategory | "unclassified" | null): string {
  return value ? categoryLabels[value] : "未分类";
}

export function ticketStatusLabel(value: TicketStatus): string {
  return statusLabels[value];
}

export function ticketPriorityLabel(value: TicketPriority): string {
  return priorityLabels[value];
}

