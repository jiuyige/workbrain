import {
  expireAuthSession,
  getAccessToken,
  getActiveOrganizationId,
} from "../auth/session";

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL?.trim() || "/api"
).replace(/\/$/, "");

interface BackendErrorEnvelope {
  code?: string;
  message?: string;
  request_id?: string;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function readError(response: Response): Promise<BackendErrorEnvelope> {
  try {
    return (await response.json()) as BackendErrorEnvelope;
  } catch {
    return {};
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const headers = new Headers(options.headers);
  const accessToken = getAccessToken();
  const organizationId = getActiveOrganizationId();

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  if (organizationId !== null) {
    headers.set("X-Organization-ID", String(organizationId));
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${normalizedPath}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const error = await readError(response);
    if (response.status === 401 && accessToken !== null) {
      expireAuthSession();
    }
    throw new ApiError(
      response.status,
      error.code || "HTTP_ERROR",
      error.message || "request failed",
      error.request_id || null,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
