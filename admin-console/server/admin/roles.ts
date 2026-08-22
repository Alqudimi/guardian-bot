import { TRPCError } from "@trpc/server";

export const ADMIN_ROLES = ["analyst", "operator", "auditor", "admin", "owner"] as const;
export type AdminRole = (typeof ADMIN_ROLES)[number];
export type GroupScope = "VIEW" | "AUDIT" | "MODERATE" | "CONFIGURE" | "OPERATE" | "OWNER";

const ROLE_SCOPES: Record<AdminRole, readonly GroupScope[]> = {
  analyst: ["VIEW"],
  operator: ["VIEW", "MODERATE"],
  auditor: ["VIEW", "AUDIT"],
  admin: ["VIEW", "AUDIT", "MODERATE", "CONFIGURE", "OPERATE"],
  owner: ["VIEW", "AUDIT", "MODERATE", "CONFIGURE", "OPERATE", "OWNER"],
};

export const isAdminRole = (role: string): role is AdminRole =>
  ADMIN_ROLES.includes(role as AdminRole);

export const roleAllows = (role: string, scope: GroupScope): boolean =>
  isAdminRole(role) && ROLE_SCOPES[role].includes(scope);

export const requireScope = (role: string, scope: GroupScope) => {
  if (roleAllows(role, scope)) return;
  throw new TRPCError({ code: "FORBIDDEN", message: "You do not have permission for this operation." });
};
