import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TrpcContext } from "../_core/context";

const mocks = vi.hoisted(() => ({
  listAccessibleGroupIds: vi.fn(),
  requireGroupAccess: vi.fn(),
  callGateway: vi.fn(),
  getGatewayDisplayConfig: vi.fn(),
  isGatewayConfigured: vi.fn(),
  probeGatewayAndRecord: vi.fn(),
  recordAdminAudit: vi.fn(),
  getPrimaryConnection: vi.fn(),
  listRecentHealth: vi.fn(),
  listOpenAlerts: vi.fn(),
  listRecentAudit: vi.fn(),
  listRecentAuditForGroups: vi.fn(),
  upsertPrimaryConnection: vi.fn(),
  bindOperator: vi.fn(),
  grantGroupScope: vi.fn(),
  listOperators: vi.fn(),
  acknowledgeAlert: vi.fn(),
  upsertOperationalAlert: vi.fn(),
  notifyOwner: vi.fn(),
}));

vi.mock("./access", () => ({ listAccessibleGroupIds: mocks.listAccessibleGroupIds, requireGroupAccess: mocks.requireGroupAccess }));
vi.mock("./gateway", () => ({ callGateway: mocks.callGateway, getGatewayDisplayConfig: mocks.getGatewayDisplayConfig, isGatewayConfigured: mocks.isGatewayConfigured }));
vi.mock("./readiness", () => ({ probeGatewayAndRecord: mocks.probeGatewayAndRecord }));
vi.mock("./repository", () => ({
  recordAdminAudit: mocks.recordAdminAudit,
  getPrimaryConnection: mocks.getPrimaryConnection,
  listRecentHealth: mocks.listRecentHealth,
  listOpenAlerts: mocks.listOpenAlerts,
  listRecentAudit: mocks.listRecentAudit,
  listRecentAuditForGroups: mocks.listRecentAuditForGroups,
  upsertPrimaryConnection: mocks.upsertPrimaryConnection,
  bindOperator: mocks.bindOperator,
  grantGroupScope: mocks.grantGroupScope,
  listOperators: mocks.listOperators,
  acknowledgeAlert: mocks.acknowledgeAlert,
  upsertOperationalAlert: mocks.upsertOperationalAlert,
}));
vi.mock("../_core/notification", () => ({ notifyOwner: mocks.notifyOwner }));

import { adminRouter } from "./router";

function context(role: "user" | "analyst" | "operator" | "admin" | "owner" = "owner"): TrpcContext {
  return {
    user: {
      id: 5,
      openId: "owner-open-id",
      name: "Owner",
      email: "owner@example.test",
      loginMethod: "manus",
      role,
      createdAt: new Date(),
      updatedAt: new Date(),
      lastSignedIn: new Date(),
    },
    req: { protocol: "https", headers: {} } as TrpcContext["req"],
    res: { clearCookie: vi.fn() } as unknown as TrpcContext["res"],
  };
}

const success = { ok: true, requestId: "req-1", availability: "AVAILABLE" as const, data: {} };

describe("adminRouter", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.requireGroupAccess.mockResolvedValue({ telegramUserId: 123456 });
    mocks.listAccessibleGroupIds.mockResolvedValue(null);
    mocks.callGateway.mockResolvedValue(success);
    mocks.recordAdminAudit.mockResolvedValue(undefined);
    mocks.upsertOperationalAlert.mockResolvedValue({ alert: { id: 1 }, created: false });
  });

  it("denies an ordinary user before a sensitive probe reaches the gateway", async () => {
    const caller = adminRouter.createCaller(context("user"));

    await expect(caller.probe()).rejects.toMatchObject({ code: "FORBIDDEN" });

    expect(mocks.probeGatewayAndRecord).not.toHaveBeenCalled();
  });

  it("sends canonical settings through the verified operator and writes an audit record", async () => {
    const caller = adminRouter.createCaller(context());

    const result = await caller.groups.updateSettings({ groupId: -1001234567890, changes: { warn_limit: "5" } });

    expect(result.ok).toBe(true);
    expect(mocks.requireGroupAccess).toHaveBeenCalledWith(expect.anything(), -1001234567890, "CONFIGURE");
    expect(mocks.callGateway).toHaveBeenCalledWith("/v1/groups/-1001234567890/settings", expect.objectContaining({ method: "PATCH", body: expect.objectContaining({ operatorTelegramId: 123456 }) }));
    expect(mocks.recordAdminAudit).toHaveBeenCalledWith(expect.objectContaining({ action: "GROUP_SETTINGS_UPDATED", outcome: "SUCCEEDED", groupId: -1001234567890 }));
  });

  it("does not hide a gateway failure behind a successful pattern audit", async () => {
    mocks.callGateway.mockResolvedValue({ ok: false, requestId: "req-2", availability: "UNAVAILABLE", error: { code: "GATEWAY_NOT_CONFIGURED", message: "not configured" } });
    const caller = adminRouter.createCaller(context());

    const result = await caller.groups.addPattern({ groupId: -1001234567890, type: "literal", category: "spam", pattern: "buy now" });

    expect(result.ok).toBe(false);
    expect(mocks.recordAdminAudit).toHaveBeenCalledWith(expect.objectContaining({ action: "GROUP_PATTERN_ADDED", outcome: "FAILED" }));
  });

  it("uses DELETE for pattern removal and requires configuration scope", async () => {
    const caller = adminRouter.createCaller(context());

    await caller.groups.removePattern({ groupId: -1001234567890, patternId: "abc123" });

    expect(mocks.callGateway).toHaveBeenCalledWith(expect.stringContaining("/patterns/abc123?operatorTelegramId=123456"), { method: "DELETE" });
    expect(mocks.requireGroupAccess).toHaveBeenCalledWith(expect.anything(), -1001234567890, "CONFIGURE");
  });

  it("records only authenticated task-free member actions with audit context", async () => {
    const caller = adminRouter.createCaller(context("operator"));

    await caller.moderation.memberAction({ groupId: -1001234567890, targetUserId: 77, action: "MUTE", durationSeconds: 300 });

    expect(mocks.callGateway).toHaveBeenCalledWith("/v1/groups/-1001234567890/members/77/actions", expect.objectContaining({ method: "POST" }));
    expect(mocks.recordAdminAudit).toHaveBeenCalledWith(expect.objectContaining({ action: "MEMBER_MUTE", targetId: "77", outcome: "SUCCEEDED" }));
  });

  it("creates a human-intervention alert when a moderation action fails", async () => {
    mocks.callGateway.mockResolvedValue({ ok: false, requestId: "req-action", availability: "DEGRADED", error: { code: "TELEGRAM_UNAVAILABLE", message: "Telegram unavailable" } });
    mocks.upsertOperationalAlert.mockResolvedValue({ alert: { id: 9 }, created: true });
    const caller = adminRouter.createCaller(context("operator"));

    const result = await caller.moderation.memberAction({ groupId: -1001234567890, targetUserId: 77, action: "BAN" });

    expect(result.ok).toBe(false);
    expect(mocks.upsertOperationalAlert).toHaveBeenCalledWith(expect.objectContaining({ source: "moderation", title: "Moderation action requires human attention" }));
    expect(mocks.notifyOwner).toHaveBeenCalledWith(expect.objectContaining({ title: "Guardian moderation action failed" }));
  });
});
