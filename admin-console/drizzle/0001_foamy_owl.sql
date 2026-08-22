CREATE TABLE `admin_audit_logs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`actorUserId` int,
	`actorTelegramId` bigint,
	`groupId` bigint,
	`action` varchar(120) NOT NULL,
	`targetType` varchar(80),
	`targetId` varchar(160),
	`outcome` enum('REQUESTED','SUCCEEDED','DENIED','FAILED','SKIPPED') NOT NULL,
	`requestId` varchar(64) NOT NULL,
	`metadata` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `admin_audit_logs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `bot_connections` (
	`id` int AUTO_INCREMENT NOT NULL,
	`name` varchar(120) NOT NULL,
	`baseUrl` varchar(2048) NOT NULL,
	`isEnabled` boolean NOT NULL DEFAULT false,
	`lastStatus` enum('AVAILABLE','DEGRADED','UNAVAILABLE','DISABLED') NOT NULL DEFAULT 'DISABLED',
	`lastHealthAt` timestamp,
	`lastErrorCode` varchar(80),
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `bot_connections_id` PRIMARY KEY(`id`),
	CONSTRAINT `bot_connections_name_unique` UNIQUE(`name`)
);
--> statement-breakpoint
CREATE TABLE `group_access_grants` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`groupId` bigint NOT NULL,
	`scope` enum('VIEW','AUDIT','MODERATE','CONFIGURE','OPERATE','OWNER') NOT NULL,
	`grantedByUserId` int,
	`expiresAt` timestamp,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `group_access_grants_id` PRIMARY KEY(`id`),
	CONSTRAINT `group_access_user_group_scope_unique` UNIQUE(`userId`,`groupId`,`scope`)
);
--> statement-breakpoint
CREATE TABLE `group_snapshots` (
	`groupId` bigint NOT NULL,
	`title` varchar(255),
	`username` varchar(128),
	`isActive` boolean NOT NULL DEFAULT true,
	`raidLockdown` boolean NOT NULL DEFAULT false,
	`slowModeActive` boolean NOT NULL DEFAULT false,
	`settings` json,
	`sourceCheckedAt` timestamp NOT NULL,
	`receivedAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `group_snapshots_groupId` PRIMARY KEY(`groupId`)
);
--> statement-breakpoint
CREATE TABLE `health_checks` (
	`id` int AUTO_INCREMENT NOT NULL,
	`connectionId` int,
	`component` enum('BOT','TELEGRAM','POSTGRES','REDIS','CELERY','DOCKER','SETTINGS','GATEWAY') NOT NULL,
	`status` enum('AVAILABLE','DEGRADED','UNAVAILABLE','DISABLED') NOT NULL,
	`durationMs` int,
	`summary` varchar(500) NOT NULL,
	`details` json,
	`requestId` varchar(64),
	`checkedAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `health_checks_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `operator_profiles` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`telegramUserId` bigint,
	`isTelegramVerified` boolean NOT NULL DEFAULT false,
	`isSuspended` boolean NOT NULL DEFAULT false,
	`lastVerifiedAt` timestamp,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `operator_profiles_id` PRIMARY KEY(`id`),
	CONSTRAINT `operator_profiles_user_unique` UNIQUE(`userId`),
	CONSTRAINT `operator_profiles_telegram_unique` UNIQUE(`telegramUserId`)
);
--> statement-breakpoint
CREATE TABLE `scheduled_job_runs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`jobId` int NOT NULL,
	`runUid` varchar(80),
	`status` enum('SUCCEEDED','FAILED','SKIPPED') NOT NULL,
	`summary` varchar(500) NOT NULL,
	`details` json,
	`startedAt` timestamp NOT NULL DEFAULT (now()),
	`completedAt` timestamp,
	CONSTRAINT `scheduled_job_runs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `scheduled_jobs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`jobKey` varchar(80) NOT NULL,
	`taskUid` varchar(65),
	`cronExpression` varchar(80) NOT NULL,
	`isEnabled` boolean NOT NULL DEFAULT false,
	`lastRunAt` timestamp,
	`lastStatus` enum('SUCCEEDED','FAILED','SKIPPED','NEVER') NOT NULL DEFAULT 'NEVER',
	`lastErrorCode` varchar(80),
	`createdByUserId` int,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `scheduled_jobs_id` PRIMARY KEY(`id`),
	CONSTRAINT `scheduled_jobs_job_key_unique` UNIQUE(`jobKey`),
	CONSTRAINT `scheduled_jobs_task_uid_unique` UNIQUE(`taskUid`)
);
--> statement-breakpoint
CREATE TABLE `system_alerts` (
	`id` int AUTO_INCREMENT NOT NULL,
	`severity` enum('INFO','WARNING','CRITICAL') NOT NULL,
	`source` varchar(80) NOT NULL,
	`fingerprint` varchar(160) NOT NULL,
	`title` varchar(240) NOT NULL,
	`summary` text NOT NULL,
	`details` json,
	`notificationDelivered` boolean NOT NULL DEFAULT false,
	`notificationAttemptedAt` timestamp,
	`acknowledgedAt` timestamp,
	`acknowledgedByUserId` int,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `system_alerts_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
ALTER TABLE `users` MODIFY COLUMN `role` enum('user','analyst','operator','auditor','admin','owner') NOT NULL DEFAULT 'user';--> statement-breakpoint
ALTER TABLE `admin_audit_logs` ADD CONSTRAINT `admin_audit_logs_actorUserId_users_id_fk` FOREIGN KEY (`actorUserId`) REFERENCES `users`(`id`) ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `group_access_grants` ADD CONSTRAINT `group_access_grants_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `group_access_grants` ADD CONSTRAINT `group_access_grants_grantedByUserId_users_id_fk` FOREIGN KEY (`grantedByUserId`) REFERENCES `users`(`id`) ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `health_checks` ADD CONSTRAINT `health_checks_connectionId_bot_connections_id_fk` FOREIGN KEY (`connectionId`) REFERENCES `bot_connections`(`id`) ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `operator_profiles` ADD CONSTRAINT `operator_profiles_userId_users_id_fk` FOREIGN KEY (`userId`) REFERENCES `users`(`id`) ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `scheduled_job_runs` ADD CONSTRAINT `scheduled_job_runs_jobId_scheduled_jobs_id_fk` FOREIGN KEY (`jobId`) REFERENCES `scheduled_jobs`(`id`) ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `scheduled_jobs` ADD CONSTRAINT `scheduled_jobs_createdByUserId_users_id_fk` FOREIGN KEY (`createdByUserId`) REFERENCES `users`(`id`) ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `system_alerts` ADD CONSTRAINT `system_alerts_acknowledgedByUserId_users_id_fk` FOREIGN KEY (`acknowledgedByUserId`) REFERENCES `users`(`id`) ON DELETE set null ON UPDATE no action;--> statement-breakpoint
CREATE INDEX `admin_audit_actor_time_idx` ON `admin_audit_logs` (`actorUserId`,`createdAt`);--> statement-breakpoint
CREATE INDEX `admin_audit_group_time_idx` ON `admin_audit_logs` (`groupId`,`createdAt`);--> statement-breakpoint
CREATE INDEX `admin_audit_request_idx` ON `admin_audit_logs` (`requestId`);--> statement-breakpoint
CREATE INDEX `group_access_group_idx` ON `group_access_grants` (`groupId`);--> statement-breakpoint
CREATE INDEX `group_snapshots_received_idx` ON `group_snapshots` (`receivedAt`);--> statement-breakpoint
CREATE INDEX `health_checks_component_time_idx` ON `health_checks` (`component`,`checkedAt`);--> statement-breakpoint
CREATE INDEX `scheduled_job_runs_job_time_idx` ON `scheduled_job_runs` (`jobId`,`startedAt`);--> statement-breakpoint
CREATE INDEX `system_alerts_created_idx` ON `system_alerts` (`createdAt`);--> statement-breakpoint
CREATE INDEX `system_alerts_fingerprint_idx` ON `system_alerts` (`fingerprint`);