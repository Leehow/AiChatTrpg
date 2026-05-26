import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useI18n } from "../../i18n";
import {
  createUserAPI,
  deleteUserAPI,
  listUsersAPI,
  updateUserAPI,
  type UserDTO,
  type UserRole,
} from "../../api/users";
import { Section } from "./primitives";

interface Props {
  /** Logged-in admin's user id, used to mark the "you" row and disable
   *  destructive operations against the caller. */
  currentUserId: string;
}

export function DebugUsersTab({ currentUserId }: Props) {
  const { t } = useI18n();
  const [users, setUsers] = useState<UserDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setUsers(await listUsersAPI());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : t("usersLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleDelete = async (u: UserDTO) => {
    const msg = t("usersDeleteConfirm").replace("{name}", u.name || u.username);
    if (!window.confirm(msg)) return;
    try {
      await deleteUserAPI(u.id);
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete");
    }
  };

  const handleToggleRole = async (u: UserDTO) => {
    const next: UserRole = u.role === "admin" ? "player" : "admin";
    try {
      await updateUserAPI(u.id, { role: next });
      await refresh();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to change role");
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <AddUserSection onCreated={refresh} />

      <Section title={t("usersTitle")}>
        {loading && (
          <div className="text-[12px] text-text-3 px-1 py-2">…</div>
        )}
        {loadError && (
          <div className="text-[12px] text-red-500 px-1 py-2">{loadError}</div>
        )}
        {!loading && !loadError && users.length === 0 && (
          <div className="text-[12px] text-text-3 px-1 py-2">
            {t("usersEmpty")}
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          {users.map((u) => (
            <UserRow
              key={u.id}
              user={u}
              isSelf={u.id === currentUserId}
              onDelete={() => handleDelete(u)}
              onToggleRole={() => handleToggleRole(u)}
            />
          ))}
        </div>
      </Section>
    </div>
  );
}

function AddUserSection({ onCreated }: { onCreated: () => Promise<void> }) {
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<UserRole>("player");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await createUserAPI({
        username: username.trim(),
        password,
        name: name.trim() || undefined,
        role,
      });
      setUsername("");
      setPassword("");
      setName("");
      setRole("player");
      await onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title={t("usersAddTitle")}>
      <form onSubmit={handleSubmit} className="flex flex-col gap-2 px-1 py-1">
        <FormRow label={t("usersUsername")}>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            className="w-full px-2 py-1 rounded bg-bg border border-border text-[12px] focus:border-accent focus:outline-none"
          />
        </FormRow>
        <FormRow label={t("usersPassword")}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            className="w-full px-2 py-1 rounded bg-bg border border-border text-[12px] focus:border-accent focus:outline-none"
          />
        </FormRow>
        <FormRow
          label={t("usersDisplayName")}
          hint={t("usersOptionalName")}
        >
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full px-2 py-1 rounded bg-bg border border-border text-[12px] focus:border-accent focus:outline-none"
          />
        </FormRow>
        <FormRow label={t("usersRole")}>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            className="w-full px-2 py-1 rounded bg-bg border border-border text-[12px] focus:border-accent focus:outline-none"
          >
            <option value="player">{t("usersRolePlayer")}</option>
            <option value="admin">{t("usersRoleAdmin")}</option>
          </select>
        </FormRow>
        {error && (
          <div className="text-[11px] text-red-500 leading-relaxed">
            {error}
          </div>
        )}
        <button
          type="submit"
          disabled={busy || !username || !password}
          className="self-start px-3 py-1.5 rounded bg-accent text-white text-[12px] font-semibold hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
        >
          {busy ? t("usersAdding") : t("usersAdd")}
        </button>
      </form>
    </Section>
  );
}

function FormRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10.5px] font-semibold tracking-[0.04em] uppercase text-text-3">
        {label}
        {hint && (
          <span className="ml-1 normal-case font-normal text-text-3">
            {hint}
          </span>
        )}
      </span>
      {children}
    </label>
  );
}

function UserRow({
  user,
  isSelf,
  onDelete,
  onToggleRole,
}: {
  user: UserDTO;
  isSelf: boolean;
  onDelete: () => void;
  onToggleRole: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded border border-border bg-bg">
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-semibold truncate flex items-center gap-1.5">
          {user.name || user.username}
          {isSelf && (
            <span className="text-[9.5px] uppercase tracking-[0.06em] text-text-3 font-normal">
              · {t("usersYou")}
            </span>
          )}
        </div>
        <div className="text-[10.5px] text-text-3 truncate">
          @{user.username}
          <span
            className={[
              "ml-2 px-1 py-px rounded text-[9.5px] uppercase tracking-[0.06em]",
              user.role === "admin"
                ? "bg-accent-dim text-[var(--accent-text)]"
                : "bg-surface-2 text-text-3",
            ].join(" ")}
          >
            {user.role === "admin" ? t("usersRoleAdmin") : t("usersRolePlayer")}
          </span>
        </div>
      </div>
      <button
        type="button"
        onClick={onToggleRole}
        disabled={isSelf && user.role === "admin"}
        title={user.role === "admin" ? t("usersDemote") : t("usersPromote")}
        className="px-1.5 py-0.5 rounded text-[10.5px] text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        {user.role === "admin" ? "↓" : "↑"}
      </button>
      <button
        type="button"
        onClick={onDelete}
        disabled={isSelf}
        title={t("usersDelete")}
        className="px-1.5 py-0.5 rounded text-[10.5px] text-text-3 hover:text-red-500 hover:bg-red-500/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
      >
        ×
      </button>
    </div>
  );
}
