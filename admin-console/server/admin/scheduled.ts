import type { Request, Response } from "express";
import { sdk } from "../_core/sdk";
import { getScheduledJobByTaskUid, recordScheduledJobRun } from "./repository";
import { probeGatewayAndRecord } from "./readiness";

export async function readinessScheduledHandler(req: Request, res: Response) {
  const startedAt = new Date();
  try {
    const user = await sdk.authenticateRequest(req as unknown as Request);
    if (!user.isCron || !user.taskUid) return res.status(403).json({ error: "cron-only" });
    const job = await getScheduledJobByTaskUid(user.taskUid);
    if (!job || job.jobKey !== "readiness" || !job.isEnabled) {
      return res.json({ ok: true, skipped: "orphan-or-disabled" });
    }
    const { result } = await probeGatewayAndRecord();
    const status = result.ok ? "SUCCEEDED" : "FAILED";
    await recordScheduledJobRun({
      jobId: job.id,
      status,
      summary: result.ok ? "Gateway readiness probe completed." : result.error?.message ?? "Gateway readiness probe failed.",
      details: result.error ? { code: result.error.code, requestId: result.requestId } : { requestId: result.requestId },
      startedAt,
      completedAt: new Date(),
    });
    if (!result.ok) return res.status(503).json({ error: result.error?.code ?? "READINESS_FAILED", requestId: result.requestId });
    return res.json({ ok: true, requestId: result.requestId });
  } catch (error) {
    return res.status(500).json({ error: "READINESS_HANDLER_FAILED", timestamp: new Date().toISOString() });
  }
}
