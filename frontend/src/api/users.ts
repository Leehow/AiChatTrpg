// Admin-only user management endpoints — see backend/routes/users.py.

import { apiFetch } from "./http";

export type UserRole = "admin" | "player";

export interface UserDTO {
  id: string;
  name: string;
  username: string;
  role: UserRole;
  created_at: string;
  updated_at: string;
}

export interface UserCreateBody {
  username: string;
  password: string;
  name?: string;
  role?: UserRole;
}

export interface UserUpdateBody {
  name?: string;
  password?: string;
  role?: UserRole;
}

const BASE = "/api/users";

export const listUsersAPI = () => apiFetch<UserDTO[]>(BASE);

export const createUserAPI = (body: UserCreateBody) =>
  apiFetch<UserDTO>(BASE, { method: "POST", json: body });

export const updateUserAPI = (id: string, body: UserUpdateBody) =>
  apiFetch<UserDTO>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PUT",
    json: body,
  });

export const deleteUserAPI = (id: string) =>
  apiFetch<{ ok: boolean }>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
