import {
  bigint,
  boolean,
  index,
  int,
  json,
  mysqlEnum,
  mysqlTable,
  text,
  timestamp,
  uniqueIndex,
  varchar,
} from "drizzle-orm/mysql-core";

export const users = mysqlTable("users", {
  id: int("id").autoincrement().primaryKey(),
  openId: varchar("openId", { length: 64 }).notNull().unique(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "analyst", "operator", "auditor", "admin", "owner"])
    .default("user")
    .notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export const operatorProfiles = mysqlTable(
  "operator_profiles",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull().references(() => users.id, { onDelete: "cascade" }),
    telegramUserId: bigint("telegramUserId", { mode: "number" }),
    isTelegramVerified: boolean("isTelegramVerified").default(false).notNull(),
    isSuspended: boolean("isSuspended").default(false).notNull(),
    lastVerifiedAt: timestamp("lastVerifiedAt"),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  table => [
    uniqueIndex("operator_profiles_user_unique").on(table.userId),
    uniqueIndex("operator_profiles_telegram_unique").on(table.telegramUserId),
  ],
);

export const groupAccessGrants = mysqlTable(
  "group_access_grants",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull().references(() => users.id, { onDelete: "cascade" }),
    groupId: bigint("groupId", { mode: "number" }).notNull(),
    scope: mysqlEnum("scope", ["VIEW", "AUDIT", "MODERATE", "CONFIGURE", "OPERATE", "OWNER"])
      .notNull(),
    grantedByUserId: int("grantedByUserId").references(() => users.id, { onDelete: "set null" }),
    expiresAt: timestamp("expiresAt"),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
  },
  table => [
    uniqueIndex("group_access_user_group_scope_unique").on(table.userId, table.groupId, table.scope),
    index("group_access_group_idx").on(table.groupId),
  ],
);

export const botConnections = mysqlTable(
  "bot_connections",
  {
    id: int("id").autoincrement().primaryKey(),
    name: varchar("name", { length: 120 }).notNull(),
    baseUrl: varchar("baseUrl", { length: 2048 }).notNull(),
    isEnabled: boolean("isEnabled").default(false).notNull(),
    lastStatus: mysqlEnum("lastStatus", ["AVAILABLE", "DEGRADED", "UNAVAILABLE", "DISABLED"])
      .default("DISABLED")
      .notNull(),
    lastHealthAt: timestamp("lastHealthAt"),
    lastErrorCode: varchar("lastErrorCode", { length: 80 }),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  table => [uniqueIndex("bot_connections_name_unique").on(table.name)],
);

export const groupSnapshots = mysqlTable(
  "group_snapshots",
  {
    groupId: bigint("groupId", { mode: "number" }).primaryKey(),
    title: varchar("title", { length: 255 }),
    username: varchar("username", { length: 128 }),
    isActive: boolean("isActive").default(true).notNull(),
    raidLockdown: boolean("raidLockdown").default(false).notNull(),
    slowModeActive: boolean("slowModeActive").default(false).notNull(),
    settings: json("settings"),
    sourceCheckedAt: timestamp("sourceCheckedAt").notNull(),
    receivedAt: timestamp("receivedAt").defaultNow().notNull(),
  },
  table => [index("group_snapshots_received_idx").on(table.receivedAt)],
);

export const healthChecks = mysqlTable(
  "health_checks",
  {
    id: int("id").autoincrement().primaryKey(),
    connectionId: int("connectionId").references(() => botConnections.id, { onDelete: "set null" }),
    component: mysqlEnum("component", ["BOT", "TELEGRAM", "POSTGRES", "REDIS", "CELERY", "DOCKER", "SETTINGS", "GATEWAY"])
      .notNull(),
    status: mysqlEnum("status", ["AVAILABLE", "DEGRADED", "UNAVAILABLE", "DISABLED"]).notNull(),
    durationMs: int("durationMs"),
    summary: varchar("summary", { length: 500 }).notNull(),
    details: json("details"),
    requestId: varchar("requestId", { length: 64 }),
    checkedAt: timestamp("checkedAt").defaultNow().notNull(),
  },
  table => [index("health_checks_component_time_idx").on(table.component, table.checkedAt)],
);

export const adminAuditLogs = mysqlTable(
  "admin_audit_logs",
  {
    id: int("id").autoincrement().primaryKey(),
    actorUserId: int("actorUserId").references(() => users.id, { onDelete: "set null" }),
    actorTelegramId: bigint("actorTelegramId", { mode: "number" }),
    groupId: bigint("groupId", { mode: "number" }),
    action: varchar("action", { length: 120 }).notNull(),
    targetType: varchar("targetType", { length: 80 }),
    targetId: varchar("targetId", { length: 160 }),
    outcome: mysqlEnum("outcome", ["REQUESTED", "SUCCEEDED", "DENIED", "FAILED", "SKIPPED"]).notNull(),
    requestId: varchar("requestId", { length: 64 }).notNull(),
    metadata: json("metadata"),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
  },
  table => [
    index("admin_audit_actor_time_idx").on(table.actorUserId, table.createdAt),
    index("admin_audit_group_time_idx").on(table.groupId, table.createdAt),
    index("admin_audit_request_idx").on(table.requestId),
  ],
);

export const systemAlerts = mysqlTable(
  "system_alerts",
  {
    id: int("id").autoincrement().primaryKey(),
    severity: mysqlEnum("severity", ["INFO", "WARNING", "CRITICAL"]).notNull(),
    source: varchar("source", { length: 80 }).notNull(),
    fingerprint: varchar("fingerprint", { length: 160 }).notNull(),
    title: varchar("title", { length: 240 }).notNull(),
    summary: text("summary").notNull(),
    details: json("details"),
    notificationDelivered: boolean("notificationDelivered").default(false).notNull(),
    notificationAttemptedAt: timestamp("notificationAttemptedAt"),
    acknowledgedAt: timestamp("acknowledgedAt"),
    acknowledgedByUserId: int("acknowledgedByUserId").references(() => users.id, { onDelete: "set null" }),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  table => [
    index("system_alerts_created_idx").on(table.createdAt),
    index("system_alerts_fingerprint_idx").on(table.fingerprint),
  ],
);

export const scheduledJobs = mysqlTable(
  "scheduled_jobs",
  {
    id: int("id").autoincrement().primaryKey(),
    jobKey: varchar("jobKey", { length: 80 }).notNull(),
    taskUid: varchar("taskUid", { length: 65 }),
    cronExpression: varchar("cronExpression", { length: 80 }).notNull(),
    isEnabled: boolean("isEnabled").default(false).notNull(),
    lastRunAt: timestamp("lastRunAt"),
    lastStatus: mysqlEnum("lastStatus", ["SUCCEEDED", "FAILED", "SKIPPED", "NEVER"])
      .default("NEVER")
      .notNull(),
    lastErrorCode: varchar("lastErrorCode", { length: 80 }),
    createdByUserId: int("createdByUserId").references(() => users.id, { onDelete: "set null" }),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  table => [
    uniqueIndex("scheduled_jobs_job_key_unique").on(table.jobKey),
    uniqueIndex("scheduled_jobs_task_uid_unique").on(table.taskUid),
  ],
);

export const scheduledJobRuns = mysqlTable(
  "scheduled_job_runs",
  {
    id: int("id").autoincrement().primaryKey(),
    jobId: int("jobId").notNull().references(() => scheduledJobs.id, { onDelete: "cascade" }),
    runUid: varchar("runUid", { length: 80 }),
    status: mysqlEnum("status", ["SUCCEEDED", "FAILED", "SKIPPED"]).notNull(),
    summary: varchar("summary", { length: 500 }).notNull(),
    details: json("details"),
    startedAt: timestamp("startedAt").defaultNow().notNull(),
    completedAt: timestamp("completedAt"),
  },
  table => [index("scheduled_job_runs_job_time_idx").on(table.jobId, table.startedAt)],
);

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;
