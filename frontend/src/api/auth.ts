// Auth endpoints — login / me / logout. The token issued by login is
// kept in localStorage by api/http.ts and attached as a Bearer header.

import {
  apiFetch,
  clearStoredAuth,
  getStoredToken,
  setStoredAuth,
  type StoredUser,
  type UserPreferences,
} from "./http";

export interface LoginResponse {
  token: string;
  user: StoredUser;
}

export interface RegistrationStatusResponse {
  enabled: boolean;
  invite_required: boolean;
}

export interface RegisterRequest {
  username: string;
  password: string;
  name?: string;
  invite_code?: string;
}

export async function loginAPI(
  username: string,
  password: string
): Promise<LoginResponse> {
  const res = await apiFetch<LoginResponse>(`/api/auth/login`, {
    method: "POST",
    json: { username, password },
    skipAuth: true,
  });
  setStoredAuth(res.token, res.user);
  return res;
}

export async function registrationStatusAPI(): Promise<RegistrationStatusResponse> {
  return apiFetch<RegistrationStatusResponse>(`/api/auth/registration-status`, {
    skipAuth: true,
  });
}

export async function registerAPI(body: RegisterRequest): Promise<LoginResponse> {
  const res = await apiFetch<LoginResponse>(`/api/auth/register`, {
    method: "POST",
    json: body,
    skipAuth: true,
  });
  setStoredAuth(res.token, res.user);
  return res;
}

export function logoutAPI(): void {
  // Server-side is stateless; we just drop the token. Fire-and-forget the
  // logout endpoint so future server-side blacklists work transparently.
  void apiFetch<unknown>(`/api/auth/logout`, { method: "POST" }).catch(() => {});
  clearStoredAuth();
}

export async function meAPI(): Promise<StoredUser> {
  return apiFetch<StoredUser>(`/api/auth/me`);
}

/** Partial-merge update. Send `null` to delete a key. Returns the updated
 * user; the cached StoredUser in localStorage is refreshed in place. */
export async function updatePreferencesAPI(
  patch: Partial<UserPreferences>
): Promise<StoredUser> {
  const updated = await apiFetch<StoredUser>(`/api/auth/preferences`, {
    method: "POST",
    json: { patch },
  });
  const token = getStoredToken();
  if (token) setStoredAuth(token, updated);
  return updated;
}
