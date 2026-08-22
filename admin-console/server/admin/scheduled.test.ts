import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authenticateRequest: vi.fn(),
  getScheduledJobByTaskUid: vi.fn(),
  recordScheduledJobRun: vi.fn(),
  probeGatewayAndRecord: vi.fn(),
}));

vi.mock("../_core/sdk", () => ({ sdk: { authenticateRequest: mocks.authenticateRequest } }));
vi.mock("./repository", () => ({ getScheduledJobByTaskUid: mocks.getScheduledJobByTaskUid, recordScheduledJobRun: mocks.recordScheduledJobRun }));
vi.mock("./readiness", () => ({ probeGatewayAndRecord: mocks.probeGatewayAndRecord }));

import { readinessScheduledHandler } from "./scheduled";

function response() {
  const res = { status: vi.fn(), json: vi.fn() };
  res.status.mockReturnValue(res);
  return res;
}

describe("scheduled readiness handler", () => {
  beforeEach(() => vi.resetAllMocks());

  it("rejects a non-cron caller", async () => {
    mocks.authenticateRequest.mockResolvedValue({ isCron: false });
    const res = response();

    await readinessScheduledHandler({ body: { taskUid: "attacker" } } as never, res as never);

    expect(res.status).toHaveBeenCalledWith(403);
    expect(mocks.getScheduledJobByTaskUid).not.toHaveBeenCalled();
  });

  it("uses the authenticated task UID and returns a non-retry orphan result", async () => {
    mocks.authenticateRequest.mockResolvedValue({ isCron: true, taskUid: "trusted-task-uid" });
    mocks.getScheduledJobByTaskUid.mockResolvedValue(null);
    const res = response();

    await readinessScheduledHandler({ body: { taskUid: "attacker-controlled" } } as never, res as never);

    expect(mocks.getScheduledJobByTaskUid).toHaveBeenCalledWith("trusted-task-uid");
    expect(res.json).toHaveBeenCalledWith({ ok: true, skipped: "orphan-or-disabled" });
    expect(mocks.probeGatewayAndRecord).not.toHaveBeenCalled();
  });

  it("records a failed probe against the durable scheduled job", async () => {
    mocks.authenticateRequest.mockResolvedValue({ isCron: true, taskUid: "trusted-task-uid" });
    mocks.getScheduledJobByTaskUid.mockResolvedValue({ id: 7, jobKey: "readiness", isEnabled: true });
    mocks.probeGatewayAndRecord.mockResolvedValue({ result: { ok: false, requestId: "req-1", error: { code: "GATEWAY_TIMEOUT", message: "timed out" } } });
    const res = response();

    await readinessScheduledHandler({} as never, res as never);

    expect(mocks.recordScheduledJobRun).toHaveBeenCalledWith(expect.objectContaining({ jobId: 7, status: "FAILED" }));
    expect(res.status).toHaveBeenCalledWith(503);
  });
});
