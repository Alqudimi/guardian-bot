import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  callGateway: vi.fn(),
  getPrimaryConnection: vi.fn(),
  recordHealthChecks: vi.fn(),
  upsertOperationalAlert: vi.fn(),
  notifyOwner: vi.fn(),
}));

vi.mock("./gateway", () => ({ callGateway: mocks.callGateway }));
vi.mock("./repository", () => ({
  getPrimaryConnection: mocks.getPrimaryConnection,
  recordHealthChecks: mocks.recordHealthChecks,
  upsertOperationalAlert: mocks.upsertOperationalAlert,
}));
vi.mock("../_core/notification", () => ({ notifyOwner: mocks.notifyOwner }));

import { probeGatewayAndRecord } from "./readiness";

describe("gateway readiness", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mocks.getPrimaryConnection.mockResolvedValue(null);
    mocks.recordHealthChecks.mockResolvedValue(undefined);
  });

  it("persists a failure and notifies the owner when a new alert is created", async () => {
    mocks.callGateway.mockResolvedValue({ ok: false, requestId: "req-1", availability: "UNAVAILABLE", error: { code: "GATEWAY_TIMEOUT", message: "timed out" } });
    mocks.upsertOperationalAlert.mockResolvedValue({ alert: { id: 1 }, created: true });
    mocks.notifyOwner.mockResolvedValue(true);

    const result = await probeGatewayAndRecord();

    expect(result.result.ok).toBe(false);
    expect(mocks.recordHealthChecks).toHaveBeenCalledWith(expect.objectContaining({ requestId: "req-1", checks: [expect.objectContaining({ component: "GATEWAY", status: "UNAVAILABLE" })] }));
    expect(mocks.upsertOperationalAlert).toHaveBeenCalledWith(expect.objectContaining({ fingerprint: "gateway:GATEWAY_TIMEOUT" }));
    expect(mocks.notifyOwner).toHaveBeenCalledWith(expect.objectContaining({ title: "Guardian Bot gateway needs attention" }));
  });

  it("does not resend an owner notification for an already-open alert", async () => {
    mocks.callGateway.mockResolvedValue({ ok: false, requestId: "req-2", availability: "UNAVAILABLE", error: { code: "GATEWAY_TIMEOUT", message: "timed out" } });
    mocks.upsertOperationalAlert.mockResolvedValue({ alert: { id: 1 }, created: false });

    await probeGatewayAndRecord();

    expect(mocks.notifyOwner).not.toHaveBeenCalled();
  });

  it("creates an owner alert when the gateway reports a real moderation threshold breach", async () => {
    mocks.callGateway
      .mockResolvedValueOnce({ ok: true, requestId: "status-1", availability: "AVAILABLE", data: { components: [] } })
      .mockResolvedValueOnce({ ok: true, requestId: "threshold-1", availability: "AVAILABLE", data: { windowSeconds: 900, threshold: 20, groups: [{ groupId: -1001234567890, eventCount: 24 }] } });
    mocks.upsertOperationalAlert.mockResolvedValue({ alert: { id: 2 }, created: true });
    mocks.notifyOwner.mockResolvedValue(true);

    await probeGatewayAndRecord();

    expect(mocks.upsertOperationalAlert).toHaveBeenCalledWith(expect.objectContaining({ source: "moderation-threshold", fingerprint: "moderation-threshold:-1001234567890:900:20" }));
    expect(mocks.notifyOwner).toHaveBeenCalledWith(expect.objectContaining({ title: "Guardian moderation threshold exceeded" }));
  });
});
