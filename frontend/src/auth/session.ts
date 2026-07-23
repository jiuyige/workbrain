const ACCESS_TOKEN_KEY = "workbrain.access_token";
const ORGANIZATION_ID_KEY = "workbrain.organization_id";
export const AUTH_SESSION_EXPIRED_EVENT = "workbrain:auth-session-expired";

export function getAccessToken(): string | null {
  const token = localStorage.getItem(ACCESS_TOKEN_KEY)?.trim();
  return token || null;
}

export function setAuthSession(accessToken: string): void {
  const normalizedToken = accessToken.trim();
  if (!normalizedToken) {
    throw new Error("access token cannot be empty");
  }

  localStorage.setItem(ACCESS_TOKEN_KEY, normalizedToken);
}

export function clearAuthSession(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(ORGANIZATION_ID_KEY);
}

export function expireAuthSession(): void {
  clearAuthSession();
  window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
}

export function getActiveOrganizationId(): number | null {
  const storedValue = localStorage.getItem(ORGANIZATION_ID_KEY);
  if (storedValue === null) {
    return null;
  }

  const organizationId = Number(storedValue);
  if (!Number.isInteger(organizationId) || organizationId <= 0) {
    return null;
  }

  return organizationId;
}

export function setActiveOrganizationId(organizationId: number): void {
  if (!Number.isInteger(organizationId) || organizationId <= 0) {
    throw new Error("organization id must be a positive integer");
  }

  localStorage.setItem(ORGANIZATION_ID_KEY, String(organizationId));
}

export function hasAuthSession(): boolean {
  return getAccessToken() !== null;
}
