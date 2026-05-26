// Shared HTTP client. Reads the auth token from localStorage and attaches
// it as a Bearer header. On 401 it clears the stored token and notifies
// listeners (App.tsx subscribes) so the UI can drop back to the login screen.

const TOKEN_KEY = "chatrpg.auth.token";
const USER_KEY = "chatrpg.auth.user";

const AUTH_EVENT = "chatrpg-auth-changed";

export interface UserPreferences {
  /** Session id the UI auto-resumes after refresh. Cleared on session delete. */
  last_active_session_id?: string | null;
  /** Per-(ruleset system, node) fold state for character-card sections.
   *  Shape: { [systemId]: { [nodeId]: "open" | "closed" } }. Managed by
   *  components/character_ui/foldStore.ts. */
  character_ui_fold?: Record<string, Record<string, "open" | "closed">>;
  // Free-form: future per-user UI prefs land here.
  [key: string]: unknown;
}

export interface StoredUser {
  id: string;
  name: string;
  username: string;
  role: "admin" | "player";
  preferences: UserPreferences;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): StoredUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredUser>;
    if (!parsed || typeof parsed !== "object") return null;
    // Tolerate old cached payloads predating the preferences field.
    return {
      id: String(parsed.id ?? ""),
      name: String(parsed.name ?? ""),
      username: String(parsed.username ?? ""),
      role: parsed.role === "admin" ? "admin" : "player",
      preferences:
        parsed.preferences && typeof parsed.preferences === "object"
          ? (parsed.preferences as UserPreferences)
          : {},
    };
  } catch {
    return null;
  }
}

export function setStoredAuth(token: string, user: StoredUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function clearStoredAuth(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.dispatchEvent(new Event(AUTH_EVENT));
}

export function onAuthChanged(handler: () => void): () => void {
  window.addEventListener(AUTH_EVENT, handler);
  // Cross-tab sync: storage events fire in other tabs when our tab writes.
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(AUTH_EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}

async function readError(res: Response): Promise<string> {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      detail = String((body as { detail: unknown }).detail);
    }
  } catch {
    // ignore
  }
  return detail;
}

export interface ApiFetchInit extends Omit<RequestInit, "body"> {
  /** Plain JSON object — will be stringified. Pass `body` in init for raw. */
  json?: unknown;
  /** Skip attaching Authorization header (used by /api/auth/login). */
  skipAuth?: boolean;
}

export async function apiFetch<T>(
  path: string,
  init: ApiFetchInit = {}
): Promise<T> {
  const { json, skipAuth, headers, ...rest } = init;
  const finalHeaders: Record<string, string> = {
    ...(headers as Record<string, string> | undefined),
  };
  if (json !== undefined) {
    finalHeaders["Content-Type"] = "application/json";
  }
  if (!skipAuth) {
    const token = getStoredToken();
    if (token) finalHeaders["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(path, {
    ...rest,
    headers: finalHeaders,
    body: json !== undefined ? JSON.stringify(json) : (rest as RequestInit).body,
  });
  if (res.status === 401) {
    clearStoredAuth();
    const detail = await readError(res);
    throw new ApiError(detail, 401);
  }
  if (!res.ok) {
    throw new ApiError(await readError(res), res.status);
  }
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}
