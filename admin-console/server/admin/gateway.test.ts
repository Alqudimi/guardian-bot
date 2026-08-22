import { afterEach, describe, expect, it } from "vitest";
import { callGateway, getGatewayDisplayConfig, isGatewayConfigured } from "./gateway";

const previousUrl = process.env.GUARDIAN_GATEWAY_URL;
const previousToken = process.env.GUARDIAN_GATEWAY_TOKEN;

afterEach(() => {
  if (previousUrl === undefined) delete process.env.GUARDIAN_GATEWAY_URL;
  else process.env.GUARDIAN_GATEWAY_URL = previousUrl;
  if (previousToken === undefined) delete process.env.GUARDIAN_GATEWAY_TOKEN;
  else process.env.GUARDIAN_GATEWAY_TOKEN = previousToken;
});

describe("Guardian control gateway configuration", () => {
  it("fails closed when the gateway secret is absent", async () => {
    delete process.env.GUARDIAN_GATEWAY_URL;
    delete process.env.GUARDIAN_GATEWAY_TOKEN;

    const result = await callGateway("/v1/status");

    expect(result.ok).toBe(false);
    expect(result.availability).toBe("UNAVAILABLE");
    expect(result.error?.code).toBe("GATEWAY_NOT_CONFIGURED");
  });

  it("does not treat an HTTP address as a configured production gateway", () => {
    process.env.GUARDIAN_GATEWAY_URL = "http://127.0.0.1:8765";
    process.env.GUARDIAN_GATEWAY_TOKEN = "test-token";

    expect(isGatewayConfigured()).toBe(false);
    expect(getGatewayDisplayConfig()).toBeNull();
  });

  it("exposes only the HTTPS address and never the shared token", () => {
    process.env.GUARDIAN_GATEWAY_URL = "https://guardian.example.test/";
    process.env.GUARDIAN_GATEWAY_TOKEN = "test-token";

    expect(isGatewayConfigured()).toBe(true);
    expect(getGatewayDisplayConfig()).toEqual({ baseUrl: "https://guardian.example.test" });
    expect(JSON.stringify(getGatewayDisplayConfig())).not.toContain("test-token");
  });
});
