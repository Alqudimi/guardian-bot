import { and, eq, gt, isNull, or } from "drizzle-orm";
import { TRPCError } from "@trpc/server";
import { groupAccessGrants, operatorProfiles, type User } from "../../drizzle/schema";
import { getDb } from "../db";
import { requireScope, type GroupScope } from "./roles";

export type OperatorBinding = {
  telegramUserId: number;
  isTelegramVerified: true;
};

export async function getOperatorBinding(userId: number): Promise<OperatorBinding | null> {
  const db = await getDb();
  if (!db) throw new TRPCError({ code: "PRECONDITION_FAILED", message: "The admin database is unavailable." });
  const profile = (await db.select().from(operatorProfiles).where(eq(operatorProfiles.userId, userId)).limit(1))[0];
  if (!profile || profile.isSuspended || !profile.isTelegramVerified || profile.telegramUserId === null) return null;
  return { telegramUserId: profile.telegramUserId, isTelegramVerified: true };
}

export async function requireGroupAccess(user: User, groupId: number, scope: GroupScope): Promise<OperatorBinding> {
  requireScope(user.role, scope);
  const operator = await getOperatorBinding(user.id);
  if (!operator) {
    throw new TRPCError({
      code: "PRECONDITION_FAILED",
      message: "A verified Telegram administrator identity is required for group operations.",
    });
  }
  if (user.role === "owner") return operator;

  const db = await getDb();
  if (!db) throw new TRPCError({ code: "PRECONDITION_FAILED", message: "The admin database is unavailable." });
  const grant = await db.select({ id: groupAccessGrants.id }).from(groupAccessGrants).where(
    and(
      eq(groupAccessGrants.userId, user.id),
      eq(groupAccessGrants.groupId, groupId),
      or(eq(groupAccessGrants.scope, scope), eq(groupAccessGrants.scope, "OWNER")),
      or(isNull(groupAccessGrants.expiresAt), gt(groupAccessGrants.expiresAt, new Date())),
    ),
  ).limit(1);
  if (!grant[0]) {
    throw new TRPCError({ code: "FORBIDDEN", message: "No active group grant permits this operation." });
  }
  return operator;
}

export async function listAccessibleGroupIds(user: User): Promise<number[] | null> {
  requireScope(user.role, "VIEW");
  if (user.role === "owner") return null;
  const db = await getDb();
  if (!db) throw new TRPCError({ code: "PRECONDITION_FAILED", message: "The admin database is unavailable." });
  const rows = await db.select({ groupId: groupAccessGrants.groupId }).from(groupAccessGrants).where(
    and(
      eq(groupAccessGrants.userId, user.id),
      or(isNull(groupAccessGrants.expiresAt), gt(groupAccessGrants.expiresAt, new Date())),
    ),
  );
  return Array.from(new Set(rows.map(row => row.groupId)));
}
