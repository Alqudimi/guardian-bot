import { and, desc, eq, inArray, sql } from "drizzle-orm";
import {
  adminAuditLogs,
  botConnections,
  healthChecks,
  groupAccessGrants,
  operatorProfiles,
  scheduledJobRuns,
  scheduledJobs,
  systemAlerts,
  users,
  type User,
} from "../../drizzle/schema";
import { getDb } from "../db";

export type AuditOutcome = "REQUESTED" | "SUCCEEDED" | "DENIED" | "FAILED" | "SKIPPED";

async function requireDb() {
  const db = await getDb();
  if (!db) throw new Error("ADMIN_DATABASE_UNAVAILABLE");
  return db;
}

export async function recordAdminAudit(input: {
  actor: User;
  actorTelegramId?: number | null;
  groupId?: number | null;
  action: string;
  targetType?: string;
  targetId?: string;
  outcome: AuditOutcome;
  requestId: string;
  metadata?: Record<string, unknown>;
}) {
  const db = await requireDb();
  await db.insert(adminAuditLogs).values({
    actorUserId: input.actor.id,
    actorTelegramId: input.actorTelegramId ?? null,
    groupId: input.groupId ?? null,
    action: input.action,
    targetType: input.targetType ?? null,
    targetId: input.targetId ?? null,
    outcome: input.outcome,
    requestId: input.requestId,
    metadata: input.metadata ?? null,
  });
}

export async function listRecentAudit(limit = 50) {
  const db = await requireDb();
  return db.select().from(adminAuditLogs).orderBy(desc(adminAuditLogs.createdAt)).limit(limit);
}

export async function listRecentAuditForGroups(groupIds: number[], limit = 50) {
  if (groupIds.length === 0) return [];
  const db = await requireDb();
  return db
    .select()
    .from(adminAuditLogs)
    .where(inArray(adminAuditLogs.groupId, groupIds))
    .orderBy(desc(adminAuditLogs.createdAt))
    .limit(limit);
}

export async function listRecentHealth(limit = 80) {
  const db = await requireDb();
  return db.select().from(healthChecks).orderBy(desc(healthChecks.checkedAt)).limit(limit);
}

export async function recordHealthChecks(input: {
  connectionId?: number | null;
  requestId: string;
  checks: Array<{
    component: "BOT" | "TELEGRAM" | "POSTGRES" | "REDIS" | "CELERY" | "DOCKER" | "SETTINGS" | "GATEWAY";
    status: "AVAILABLE" | "DEGRADED" | "UNAVAILABLE" | "DISABLED";
    durationMs?: number | null;
    summary: string;
    details?: Record<string, unknown>;
  }>;
}) {
  if (input.checks.length === 0) return;
  const db = await requireDb();
  await db.insert(healthChecks).values(
    input.checks.map(check => ({
      connectionId: input.connectionId ?? null,
      component: check.component,
      status: check.status,
      durationMs: check.durationMs ?? null,
      summary: check.summary,
      details: check.details ?? null,
      requestId: input.requestId,
    })),
  );
}

export async function getPrimaryConnection() {
  const db = await requireDb();
  const rows = await db.select().from(botConnections).where(eq(botConnections.name, "primary")).limit(1);
  return rows[0] ?? null;
}

export async function upsertPrimaryConnection(input: { baseUrl: string; enabled: boolean }) {
  const db = await requireDb();
  await db.insert(botConnections).values({ name: "primary", baseUrl: input.baseUrl, isEnabled: input.enabled }).onDuplicateKeyUpdate({
    set: { baseUrl: input.baseUrl, isEnabled: input.enabled },
  });
  return getPrimaryConnection();
}

export async function listOpenAlerts(limit = 30) {
  const db = await requireDb();
  return db.select().from(systemAlerts).where(sql`${systemAlerts.acknowledgedAt} IS NULL`).orderBy(desc(systemAlerts.createdAt)).limit(limit);
}

export async function acknowledgeAlert(alertId: number, actorUserId: number) {
  const db = await requireDb();
  await db.update(systemAlerts).set({ acknowledgedAt: new Date(), acknowledgedByUserId: actorUserId }).where(eq(systemAlerts.id, alertId));
}

export async function upsertOperationalAlert(input: {
  severity: "INFO" | "WARNING" | "CRITICAL";
  source: string;
  fingerprint: string;
  title: string;
  summary: string;
  details?: Record<string, unknown>;
}) {
  const db = await requireDb();
  const existing = await db.select().from(systemAlerts).where(
    and(eq(systemAlerts.fingerprint, input.fingerprint), sql`${systemAlerts.acknowledgedAt} IS NULL`),
  ).limit(1);
  if (existing[0]) return { alert: existing[0], created: false };
  await db.insert(systemAlerts).values({ ...input, details: input.details ?? null });
  const alert = (await db.select().from(systemAlerts).where(eq(systemAlerts.fingerprint, input.fingerprint)).orderBy(desc(systemAlerts.id)).limit(1))[0];
  return { alert, created: true };
}

export async function getScheduledJobByTaskUid(taskUid: string) {
  const db = await requireDb();
  return (await db.select().from(scheduledJobs).where(eq(scheduledJobs.taskUid, taskUid)).limit(1))[0] ?? null;
}

export async function recordScheduledJobRun(input: {
  jobId: number;
  status: "SUCCEEDED" | "FAILED" | "SKIPPED";
  summary: string;
  details?: Record<string, unknown>;
  startedAt: Date;
  completedAt: Date;
}) {
  const db = await requireDb();
  await db.insert(scheduledJobRuns).values({
    jobId: input.jobId,
    status: input.status,
    summary: input.summary,
    details: input.details ?? null,
    startedAt: input.startedAt,
    completedAt: input.completedAt,
  });
  await db.update(scheduledJobs).set({
    lastRunAt: input.completedAt,
    lastStatus: input.status,
    lastErrorCode: input.status === "FAILED" ? String(input.details?.code ?? "READINESS_FAILED") : null,
  }).where(eq(scheduledJobs.id, input.jobId));
}

export async function listOperators() {
  const db = await requireDb();
  return db.select({
    user: users,
    profile: operatorProfiles,
  }).from(users).leftJoin(operatorProfiles, eq(operatorProfiles.userId, users.id)).orderBy(desc(users.lastSignedIn));
}

export async function bindOperator(input: { userId: number; telegramUserId: number }) {
  const db = await requireDb();
  await db.insert(operatorProfiles).values({
    userId: input.userId,
    telegramUserId: input.telegramUserId,
    isTelegramVerified: true,
    isSuspended: false,
    lastVerifiedAt: new Date(),
  }).onDuplicateKeyUpdate({
    set: {
      telegramUserId: input.telegramUserId,
      isTelegramVerified: true,
      isSuspended: false,
      lastVerifiedAt: new Date(),
    },
  });
}

export async function grantGroupScope(input: { userId: number; groupId: number; scope: "VIEW" | "AUDIT" | "MODERATE" | "CONFIGURE" | "OPERATE" | "OWNER"; grantedByUserId: number; expiresAt?: Date | null }) {
  const db = await requireDb();
  await db.insert(groupAccessGrants).values(input).onDuplicateKeyUpdate({
    set: { expiresAt: input.expiresAt ?? null, grantedByUserId: input.grantedByUserId },
  });
}
