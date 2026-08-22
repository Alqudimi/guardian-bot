import { TRPCError } from "@trpc/server";
import { z } from "zod";
import { adminProcedure, ownerProcedure, protectedProcedure, router, scopedProcedure } from "../_core/trpc";
import { notifyOwner } from "../_core/notification";
import { listAccessibleGroupIds, requireGroupAccess } from "./access";
import { callGateway, getGatewayDisplayConfig, isGatewayConfigured } from "./gateway";
import { probeGatewayAndRecord } from "./readiness";
import {
  acknowledgeAlert,
  bindOperator,
  getPrimaryConnection,
  grantGroupScope,
  listOpenAlerts,
  listOperators,
  listRecentAudit,
  listRecentAuditForGroups,
  listRecentHealth,
  recordAdminAudit,
  upsertOperationalAlert,
  upsertPrimaryConnection,
} from "./repository";

const groupIdInput = z.object({ groupId: z.number().int().safe() });
const scopeInput = z.enum(["VIEW", "AUDIT", "MODERATE", "CONFIGURE", "OPERATE", "OWNER"]);

export const adminRouter = router({
  overview: protectedProcedure.query(async () => ({
    gatewayConfigured: isGatewayConfigured(),
    gateway: getGatewayDisplayConfig(),
    connection: await getPrimaryConnection(),
    health: await listRecentHealth(24),
    alerts: await listOpenAlerts(12),
  })),

  probe: adminProcedure.mutation(async ({ ctx }) => {
    const { result, status } = await probeGatewayAndRecord();
    await recordAdminAudit({
      actor: ctx.user,
      action: "GATEWAY_PROBE",
      outcome: result.ok ? "SUCCEEDED" : "FAILED",
      requestId: result.requestId,
      metadata: { availability: result.availability, errorCode: result.error?.code ?? null },
    });
    return { ...result, data: status ?? result.data };
  }),

  configureConnection: ownerProcedure.mutation(async ({ ctx }) => {
    const configured = getGatewayDisplayConfig();
    if (!configured) {
      throw new TRPCError({ code: "PRECONDITION_FAILED", message: "The gateway URL and token must be configured as server secrets first." });
    }
    const connection = await upsertPrimaryConnection({ baseUrl: configured.baseUrl, enabled: true });
    await recordAdminAudit({ actor: ctx.user, action: "GATEWAY_CONNECTION_REGISTERED", outcome: "SUCCEEDED", requestId: crypto.randomUUID(), metadata: { enabled: true } });
    return connection;
  }),

  access: router({
    operators: ownerProcedure.query(() => listOperators()),
    bindOperator: ownerProcedure.input(z.object({ userId: z.number().int().positive(), telegramUserId: z.number().int().safe().positive() })).mutation(async ({ ctx, input }) => {
      await bindOperator(input);
      await recordAdminAudit({ actor: ctx.user, action: "OPERATOR_BOUND", outcome: "SUCCEEDED", requestId: crypto.randomUUID(), targetType: "WEB_USER", targetId: String(input.userId), metadata: { telegramUserId: input.telegramUserId } });
      return { success: true };
    }),
    grantGroup: ownerProcedure.input(z.object({ userId: z.number().int().positive(), groupId: z.number().int().safe(), scope: scopeInput, expiresAt: z.date().nullable().optional() })).mutation(async ({ ctx, input }) => {
      await grantGroupScope({ ...input, grantedByUserId: ctx.user.id });
      await recordAdminAudit({ actor: ctx.user, groupId: input.groupId, action: "GROUP_SCOPE_GRANTED", outcome: "SUCCEEDED", requestId: crypto.randomUUID(), targetType: "WEB_USER", targetId: String(input.userId), metadata: { scope: input.scope, expiresAt: input.expiresAt?.toISOString() ?? null } });
      return { success: true };
    }),
  }),

  audit: router({
    list: scopedProcedure("AUDIT").input(z.object({ limit: z.number().int().min(1).max(100).default(50) })).query(async ({ ctx, input }) => {
      const allowedGroupIds = await listAccessibleGroupIds(ctx.user);
      return allowedGroupIds === null ? listRecentAudit(input.limit) : listRecentAuditForGroups(allowedGroupIds, input.limit);
    }),
  }),

  alerts: router({
    list: scopedProcedure("AUDIT").input(z.object({ limit: z.number().int().min(1).max(100).default(30) })).query(({ input }) => listOpenAlerts(input.limit)),
    acknowledge: scopedProcedure("AUDIT").input(z.object({ alertId: z.number().int().positive() })).mutation(async ({ ctx, input }) => {
      await acknowledgeAlert(input.alertId, ctx.user.id);
      await recordAdminAudit({ actor: ctx.user, action: "ALERT_ACKNOWLEDGED", outcome: "SUCCEEDED", requestId: crypto.randomUUID(), targetType: "SYSTEM_ALERT", targetId: String(input.alertId) });
      return { success: true };
    }),
  }),

  groups: router({
    list: scopedProcedure("VIEW").query(async ({ ctx }) => {
      const result = await callGateway<{ groups?: Array<{ id?: number }> }>("/v1/groups");
      if (!result.ok) return result;
      const allowedGroupIds = await listAccessibleGroupIds(ctx.user);
      if (allowedGroupIds === null) return result;
      const allowed = new Set(allowedGroupIds);
      return { ...result, data: { groups: (result.data?.groups ?? []).filter(group => typeof group.id === "number" && allowed.has(group.id)) } };
    }),
    settings: scopedProcedure("VIEW").input(groupIdInput).query(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "VIEW");
      return callGateway<unknown>(`/v1/groups/${input.groupId}/settings?operatorTelegramId=${operator.telegramUserId}`);
    }),
    updateSettings: scopedProcedure("CONFIGURE").input(groupIdInput.extend({ changes: z.record(z.string(), z.string()).refine(value => Object.keys(value).length > 0 && Object.keys(value).length <= 23) })).mutation(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "CONFIGURE");
      const result = await callGateway<unknown>(`/v1/groups/${input.groupId}/settings`, { method: "PATCH", body: { operatorTelegramId: operator.telegramUserId, changes: input.changes } });
      await recordAdminAudit({ actor: ctx.user, actorTelegramId: operator.telegramUserId, groupId: input.groupId, action: "GROUP_SETTINGS_UPDATED", outcome: result.ok ? "SUCCEEDED" : "FAILED", requestId: result.requestId, metadata: { fields: Object.keys(input.changes), availability: result.availability, errorCode: result.error?.code ?? null } });
      return result;
    }),
    patterns: scopedProcedure("VIEW").input(groupIdInput).query(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "VIEW");
      return callGateway<unknown>(`/v1/groups/${input.groupId}/patterns?operatorTelegramId=${operator.telegramUserId}`);
    }),
    addPattern: scopedProcedure("CONFIGURE").input(groupIdInput.extend({ type: z.enum(["regex", "literal"]), category: z.enum(["spam", "scam", "adult", "phishing", "abuse", "other"]), pattern: z.string().min(1).max(512) })).mutation(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "CONFIGURE");
      const result = await callGateway<unknown>(`/v1/groups/${input.groupId}/patterns`, { method: "POST", body: { operatorTelegramId: operator.telegramUserId, type: input.type, category: input.category, pattern: input.pattern } });
      await recordAdminAudit({ actor: ctx.user, actorTelegramId: operator.telegramUserId, groupId: input.groupId, action: "GROUP_PATTERN_ADDED", outcome: result.ok ? "SUCCEEDED" : "FAILED", requestId: result.requestId, metadata: { type: input.type, category: input.category, availability: result.availability, errorCode: result.error?.code ?? null } });
      return result;
    }),
    removePattern: scopedProcedure("CONFIGURE").input(groupIdInput.extend({ patternId: z.string().min(1).max(32) })).mutation(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "CONFIGURE");
      const result = await callGateway<unknown>(`/v1/groups/${input.groupId}/patterns/${encodeURIComponent(input.patternId)}?operatorTelegramId=${operator.telegramUserId}`, { method: "DELETE" });
      await recordAdminAudit({ actor: ctx.user, actorTelegramId: operator.telegramUserId, groupId: input.groupId, action: "GROUP_PATTERN_REMOVED", outcome: result.ok ? "SUCCEEDED" : "FAILED", requestId: result.requestId, targetType: "GROUP_PATTERN", targetId: input.patternId, metadata: { availability: result.availability, errorCode: result.error?.code ?? null } });
      return result;
    }),
    report: scopedProcedure("AUDIT").input(groupIdInput.extend({ days: z.number().int().min(1).max(90).default(7) })).query(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "AUDIT");
      return callGateway<unknown>(`/v1/groups/${input.groupId}/report?days=${input.days}&operatorTelegramId=${operator.telegramUserId}`);
    }),
  }),

  moderation: router({
    listEvents: scopedProcedure("AUDIT").input(z.object({ groupId: z.number().int().safe(), userId: z.number().int().safe().optional(), limit: z.number().int().min(1).max(100).default(50) })).query(async ({ ctx, input }) => {
      await requireGroupAccess(ctx.user, input.groupId, "AUDIT");
      const params = new URLSearchParams({ groupId: String(input.groupId), limit: String(input.limit) });
      if (input.userId !== undefined) params.set("userId", String(input.userId));
      return callGateway<unknown>(`/v1/moderation-events?${params.toString()}`);
    }),
    memberAction: scopedProcedure("MODERATE").input(z.object({ groupId: z.number().int().safe(), targetUserId: z.number().int().safe(), action: z.enum(["RESET_WARNS", "MUTE", "UNMUTE", "BAN", "UNBAN", "KICK", "UNDO"]), durationSeconds: z.number().int().min(60).max(2_592_000).optional() })).mutation(async ({ ctx, input }) => {
      const operator = await requireGroupAccess(ctx.user, input.groupId, "MODERATE");
      const result = await callGateway<unknown>(`/v1/groups/${input.groupId}/members/${input.targetUserId}/actions`, { method: "POST", body: { operatorTelegramId: operator.telegramUserId, action: input.action, durationSeconds: input.durationSeconds } });
      await recordAdminAudit({ actor: ctx.user, actorTelegramId: operator.telegramUserId, groupId: input.groupId, action: `MEMBER_${input.action}`, targetType: "TELEGRAM_USER", targetId: String(input.targetUserId), outcome: result.ok ? "SUCCEEDED" : "FAILED", requestId: result.requestId, metadata: { availability: result.availability, errorCode: result.error?.code ?? null } });
      if (!result.ok) {
        const alert = await upsertOperationalAlert({
          severity: "WARNING",
          source: "moderation",
          fingerprint: `moderation:${input.groupId}:${input.targetUserId}:${input.action}:${result.error?.code ?? "unknown"}`,
          title: "Moderation action requires human attention",
          summary: result.error?.message ?? "A requested moderation action did not complete.",
          details: { action: input.action, groupId: input.groupId, targetUserId: input.targetUserId, requestId: result.requestId, code: result.error?.code ?? null },
        });
        if (alert.created) {
          try {
            await notifyOwner({ title: "Guardian moderation action failed", content: `${input.action} for group ${input.groupId} needs review. Request: ${result.requestId}` });
          } catch {
            // The durable alert remains available if owner delivery is unavailable.
          }
        }
      }
      return result;
    }),
  }),
});
