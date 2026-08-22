import { NOT_ADMIN_ERR_MSG, UNAUTHED_ERR_MSG } from '@shared/const';
import { initTRPC, TRPCError } from "@trpc/server";
import superjson from "superjson";
import type { TrpcContext } from "./context";
import { isAdminRole, requireScope, type GroupScope } from "../admin/roles";

const t = initTRPC.context<TrpcContext>().create({
  transformer: superjson,
});

export const router = t.router;
export const publicProcedure = t.procedure;

const requireUser = t.middleware(async opts => {
  const { ctx, next } = opts;

  if (!ctx.user) {
    throw new TRPCError({ code: "UNAUTHORIZED", message: UNAUTHED_ERR_MSG });
  }

  return next({
    ctx: {
      ...ctx,
      user: ctx.user,
    },
  });
});

export const protectedProcedure = t.procedure.use(requireUser);

export const adminProcedure = t.procedure.use(
  t.middleware(async opts => {
    const { ctx, next } = opts;

    if (!ctx.user || !isAdminRole(ctx.user.role)) {
      throw new TRPCError({ code: "FORBIDDEN", message: NOT_ADMIN_ERR_MSG });
    }

    return next({
      ctx: {
        ...ctx,
        user: ctx.user,
      },
    });
  }),
);

export const ownerProcedure = t.procedure.use(
  t.middleware(async opts => {
    if (!opts.ctx.user || opts.ctx.user.role !== "owner") {
      throw new TRPCError({ code: "FORBIDDEN", message: "Only the system owner may perform this operation." });
    }
    return opts.next({ ctx: { ...opts.ctx, user: opts.ctx.user } });
  }),
);

export const scopedProcedure = (scope: GroupScope) =>
  protectedProcedure.use(
    t.middleware(async opts => {
      const user = opts.ctx.user;
      if (!user) {
        throw new TRPCError({ code: "UNAUTHORIZED", message: UNAUTHED_ERR_MSG });
      }
      requireScope(user.role, scope);
      return opts.next({ ctx: { ...opts.ctx, user } });
    }),
  );
