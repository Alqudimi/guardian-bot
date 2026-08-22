import { z } from "zod";
import { notifyOwner } from "../_core/notification";
import { callGateway } from "./gateway";
import { getPrimaryConnection, recordHealthChecks, upsertOperationalAlert } from "./repository";

const component = z.enum(["BOT", "TELEGRAM", "POSTGRES", "REDIS", "CELERY", "DOCKER", "SETTINGS", "GATEWAY"]);
const availability = z.enum(["AVAILABLE", "DEGRADED", "UNAVAILABLE", "DISABLED"]);
const gatewayStatusSchema = z.object({
  components: z.array(z.object({
    component,
    status: availability,
    summary: z.string().max(500),
    durationMs: z.number().int().nonnegative().nullable().optional(),
    details: z.record(z.string(), z.unknown()).optional(),
  })).default([]),
  checkedAt: z.string().optional(),
});
const moderationThresholdSchema = z.object({
  windowSeconds: z.number().int().positive(),
  threshold: z.number().int().positive(),
  groups: z.array(z.object({ groupId: z.number().int().safe(), eventCount: z.number().int().nonnegative() })),
});

export async function probeGatewayAndRecord() {
  const result = await callGateway<unknown>("/v1/status");
  const connection = await getPrimaryConnection();
  const parsed = result.ok ? gatewayStatusSchema.safeParse(result.data) : null;
  const checks = parsed?.success
    ? parsed.data.components
    : [{
        component: "GATEWAY" as const,
        status: result.availability,
        summary: result.error?.message ?? "The bot gateway did not return a status result.",
        details: result.error ? { code: result.error.code } : undefined,
      }];
  await recordHealthChecks({ connectionId: connection?.id ?? null, requestId: result.requestId, checks });
  if (!result.ok && result.availability !== "DISABLED") {
    const alert = await upsertOperationalAlert({
      severity: "WARNING",
      source: "gateway",
      fingerprint: `gateway:${result.error?.code ?? "unknown"}`,
      title: "Guardian Bot gateway is unavailable",
      summary: result.error?.message ?? "The control gateway did not return a usable result.",
      details: result.error ? { code: result.error.code, requestId: result.requestId } : { requestId: result.requestId },
    });
    if (alert.created) {
      try {
        await notifyOwner({
          title: "Guardian Bot gateway needs attention",
          content: `Readiness reported ${result.error?.code ?? "an unavailable gateway"}. Request: ${result.requestId}`,
        });
      } catch {
        // The durable alert remains the source of truth when owner delivery is unavailable.
      }
    }
  }
  if (result.ok) {
    const thresholdResult = await callGateway<unknown>("/v1/ops/moderation-thresholds?windowSeconds=900&threshold=20");
    const thresholds = thresholdResult.ok ? moderationThresholdSchema.safeParse(thresholdResult.data) : null;
    if (thresholds?.success) {
      for (const group of thresholds.data.groups) {
        const alert = await upsertOperationalAlert({
          severity: "WARNING",
          source: "moderation-threshold",
          fingerprint: `moderation-threshold:${group.groupId}:${thresholds.data.windowSeconds}:${thresholds.data.threshold}`,
          title: "Moderation activity threshold exceeded",
          summary: `${group.eventCount} moderation events reached the threshold of ${thresholds.data.threshold} within ${thresholds.data.windowSeconds} seconds.`,
          details: { groupId: group.groupId, eventCount: group.eventCount, windowSeconds: thresholds.data.windowSeconds, threshold: thresholds.data.threshold, requestId: thresholdResult.requestId },
        });
        if (alert.created) {
          try {
            await notifyOwner({ title: "Guardian moderation threshold exceeded", content: `Group ${group.groupId} recorded ${group.eventCount} moderation events in the configured window.` });
          } catch {
            // Durable operational alert remains available when owner delivery is unavailable.
          }
        }
      }
    }
  }
  return { result, status: parsed?.success ? parsed.data : null };
}
