import "vue-router";

import type { RoleCode } from "@/types/api";

export {};

declare module "vue-router" {
  interface RouteMeta {
    public?: boolean;
    requiresAuth?: boolean;
    roles?: RoleCode[];
    title?: string;
    analyticsPanel?: "overview" | "consultations" | "categories" | "satisfaction" | "ai-runs";
  }
}
