import {
  clearAuthSession,
  getAccessToken,
  getActiveOrganizationId,
  setActiveOrganizationId,
  setAuthSession,
} from "./session";

describe("auth session storage", () => {
  it("stores and clears only the authentication session fields", () => {
    localStorage.setItem("unrelated", "keep-me");

    setAuthSession("jwt-token");
    setActiveOrganizationId(42);

    expect(getAccessToken()).toBe("jwt-token");
    expect(getActiveOrganizationId()).toBe(42);

    clearAuthSession();

    expect(getAccessToken()).toBeNull();
    expect(getActiveOrganizationId()).toBeNull();
    expect(localStorage.getItem("unrelated")).toBe("keep-me");
  });

  it("ignores an invalid organization id from storage", () => {
    localStorage.setItem("workbrain.organization_id", "not-an-id");

    expect(getActiveOrganizationId()).toBeNull();
  });
});
