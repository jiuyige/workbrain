import { apiRequest } from "../api/client";

export interface CurrentUser {
  id: number;
  username: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
}

interface RegisterResponse extends CurrentUser {
  message: string;
}

export function loginUser(
  username: string,
  password: string,
): Promise<TokenResponse> {
  return apiRequest<TokenResponse>("/users/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function registerUser(
  username: string,
  password: string,
): Promise<RegisterResponse> {
  return apiRequest<RegisterResponse>("/users/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function getCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/users/me");
}
