import { z } from "zod";

const availabilitySchema = z.enum(["AVAILABLE", "DEGRADED", "UNAVAILABLE", "DISABLED"]);

export type GatewayAvailability = z.infer<typeof availabilitySchema>;

export type GatewayResult<T> = {
  ok: boolean;
  requestId: string;
  availability: GatewayAvailability;
  data?: T;
  error?: { code: string; message: string };
};

const envelopeSchema = z.object({
  ok: z.boolean(),
  requestId: z.string().min(1).max(64),
  availability: availabilitySchema,
  data: z.unknown().optional(),
  error: z.object({ code: z.string(), message: z.string() }).optional(),
});

const createRequestId = () => crypto.randomUUID();

const unavailable = (requestId: string, code: string, message: string): GatewayResult<never> => ({
  ok: false,
  requestId,
  availability: "UNAVAILABLE",
  error: { code, message },
});

const getGatewayConfig = () => {
  const baseUrl = process.env.GUARDIAN_GATEWAY_URL?.trim();
  const token = process.env.GUARDIAN_GATEWAY_TOKEN?.trim();
  if (!baseUrl || !token) return null;
  try {
    const url = new URL(baseUrl);
    if (url.protocol !== "https:") return null;
    return { baseUrl: url.toString().replace(/\/$/, ""), token };
  } catch {
    return null;
  }
};

export const isGatewayConfigured = () => Boolean(getGatewayConfig());

export const getGatewayDisplayConfig = () => {
  const config = getGatewayConfig();
  return config ? { baseUrl: config.baseUrl } : null;
};

export async function callGateway<T>(
  path: string,
  init: { method?: "GET" | "POST" | "PATCH" | "DELETE"; body?: unknown } = {},
): Promise<GatewayResult<T>> {
  const requestId = createRequestId();
  const config = getGatewayConfig();
  if (!config) {
    return unavailable(requestId, "GATEWAY_NOT_CONFIGURED", "The bot control gateway is not configured.");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(`${config.baseUrl}${path}`, {
      method: init.method ?? "GET",
      headers: {
        Authorization: `Bearer ${config.token}`,
        "Content-Type": "application/json",
        "X-Request-Id": requestId,
      },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: controller.signal,
    });
    const payload = envelopeSchema.safeParse(await response.json().catch(() => null));
    if (!payload.success) {
      return unavailable(requestId, "GATEWAY_INVALID_RESPONSE", "The bot gateway returned an invalid response.");
    }
    return payload.data as GatewayResult<T>;
  } catch {
    return unavailable(requestId, "GATEWAY_UNREACHABLE", "The bot control gateway is unreachable.");
  } finally {
    clearTimeout(timeout);
  }
}
