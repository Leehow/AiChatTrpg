import { apiFetch, getStoredToken } from "./http";

export interface MusicTrackDTO {
  id: string;
  title: string;
  source_type: "url" | "upload";
  url: string;
  is_public: boolean;
  owner_id: string;
  owner_username: string;
  is_mine: boolean;
  created_at: string;
  updated_at: string;
}

const BASE = "/api/music";

export const listMusicAPI = () => apiFetch<MusicTrackDTO[]>(BASE);

export const createMusicFromUrlAPI = (body: {
  url: string;
  title?: string;
  is_public?: boolean;
}) =>
  apiFetch<MusicTrackDTO>(BASE, {
    method: "POST",
    json: {
      url: body.url,
      title: body.title ?? "",
      is_public: body.is_public ?? true,
    },
  });

export const updateMusicAPI = (
  id: string,
  body: { title?: string; is_public?: boolean },
) =>
  apiFetch<MusicTrackDTO>(`${BASE}/${id}`, {
    method: "PUT",
    json: body,
  });

export const deleteMusicAPI = (id: string) =>
  apiFetch<{ ok: boolean }>(`${BASE}/${id}`, { method: "DELETE" });

// Upload uses multipart/form-data, so we bypass the JSON helper.
export async function uploadMusicAPI(
  file: File,
  opts: { title?: string; is_public?: boolean } = {},
): Promise<MusicTrackDTO> {
  const form = new FormData();
  form.append("file", file);
  form.append("title", opts.title ?? "");
  form.append("is_public", String(opts.is_public ?? true));
  const headers: Record<string, string> = {};
  const token = getStoredToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE}/upload`, {
    method: "POST",
    body: form,
    headers,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        detail = String((body as { detail: unknown }).detail);
      }
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  return (await res.json()) as MusicTrackDTO;
}
