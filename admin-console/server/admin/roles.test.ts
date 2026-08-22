import { describe, expect, it } from "vitest";
import { isAdminRole, roleAllows } from "./roles";

describe("admin roles", () => {
  it("accepts only declared administrative roles", () => {
    expect(isAdminRole("owner")).toBe(true);
    expect(isAdminRole("operator")).toBe(true);
    expect(isAdminRole("user")).toBe(false);
  });

  it("keeps configuration and operational privileges distinct", () => {
    expect(roleAllows("analyst", "VIEW")).toBe(true);
    expect(roleAllows("analyst", "MODERATE")).toBe(false);
    expect(roleAllows("operator", "MODERATE")).toBe(true);
    expect(roleAllows("operator", "CONFIGURE")).toBe(false);
    expect(roleAllows("admin", "CONFIGURE")).toBe(true);
    expect(roleAllows("owner", "OWNER")).toBe(true);
  });
});
