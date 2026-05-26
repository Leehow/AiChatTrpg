import { useEffect, useState, type FormEvent } from "react";
import {
  loginAPI,
  registerAPI,
  registrationStatusAPI,
  type RegistrationStatusResponse,
} from "../api/auth";
import { ApiError } from "../api/http";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { useI18n } from "../i18n";

export interface LoginPageProps {
  onLoggedIn: () => void;
}

export function LoginPage({ onLoggedIn }: LoginPageProps) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [registrationStatus, setRegistrationStatus] =
    useState<RegistrationStatusResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    registrationStatusAPI()
      .then((status) => {
        if (!cancelled) setRegistrationStatus(status);
      })
      .catch(() => {
        if (!cancelled) {
          setRegistrationStatus({ enabled: false, invite_required: true });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const registrationEnabled = registrationStatus?.enabled ?? false;
  const isRegister = mode === "register" && registrationEnabled;
  const inviteRequired = Boolean(registrationStatus?.invite_required);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      if (isRegister) {
        await registerAPI({
          username: username.trim(),
          password,
          name: name.trim() || undefined,
          invite_code: inviteCode.trim() || undefined,
        });
      } else {
        await loginAPI(username.trim(), password);
      }
      onLoggedIn();
    } catch (err) {
      if (!isRegister && err instanceof ApiError && err.status === 401) {
        setError(t("loginInvalid"));
      } else if (isRegister && err instanceof ApiError && err.status === 409) {
        setError(t("registerUsernameTaken"));
      } else if (isRegister && err instanceof ApiError && err.status === 403) {
        setError(
          err.message === "registration disabled"
            ? t("registrationUnavailable")
            : t("registerInviteInvalid")
        );
      } else if (isRegister && err instanceof ApiError && err.status === 422) {
        setError(t("registerInvalid"));
      } else {
        setError(err instanceof Error ? err.message : t("loginInvalid"));
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-full w-full flex items-center justify-center bg-bg text-text px-4 py-12 relative">
      <div className="absolute top-4 right-4">
        <LanguageSwitcher />
      </div>
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm bg-surface border border-border rounded-lg p-7 shadow-lg flex flex-col gap-4"
      >
        <div className="flex items-center gap-2 mb-1">
          <img
            src="/logo/chatrpg-logo-warm-transparent.png"
            alt=""
            aria-hidden="true"
            className="h-8 w-8 object-contain"
          />
          <div className="text-lg font-semibold tracking-tight">
            chat<span className="text-accent">rpg</span>
          </div>
        </div>

        <div>
          <h1 className="text-base font-semibold mb-1">
            {isRegister ? t("registerTitle") : t("loginTitle")}
          </h1>
          <p className="text-xs text-text-3">
            {isRegister ? t("registerSubtitle") : t("loginSubtitle")}
          </p>
        </div>

        {registrationEnabled && (
          <div className="grid grid-cols-2 rounded-lg border border-border overflow-hidden text-xs font-semibold">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setError(null);
              }}
              className={`px-3 py-2 transition-colors ${
                !isRegister
                  ? "bg-accent text-white"
                  : "bg-bg text-text-2 hover:text-text"
              }`}
            >
              {t("loginTab")}
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("register");
                setError(null);
              }}
              className={`px-3 py-2 transition-colors ${
                isRegister
                  ? "bg-accent text-white"
                  : "bg-bg text-text-2 hover:text-text"
              }`}
            >
              {t("registerTab")}
            </button>
          </div>
        )}

        {isRegister && (
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold text-text-2 tracking-[0.04em]">
              {t("registerName")}
            </span>
            <input
              type="text"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("registerNamePlaceholder")}
              className="px-3 py-2 rounded-lg bg-bg border border-border focus:border-accent focus:outline-none text-sm transition-colors"
            />
          </label>
        )}

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-text-2 tracking-[0.04em]">
            {t("loginUsername")}
          </span>
          <input
            type="text"
            autoComplete="username"
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t("loginUsernamePlaceholder")}
            className="px-3 py-2 rounded-lg bg-bg border border-border focus:border-accent focus:outline-none text-sm transition-colors"
            required
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-text-2 tracking-[0.04em]">
            {t("loginPassword")}
          </span>
          <input
            type="password"
            autoComplete={isRegister ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t("loginPasswordPlaceholder")}
            className="px-3 py-2 rounded-lg bg-bg border border-border focus:border-accent focus:outline-none text-sm transition-colors"
            required
          />
        </label>

        {isRegister && inviteRequired && (
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-semibold text-text-2 tracking-[0.04em]">
              {t("registerInviteCode")}
            </span>
            <input
              type="text"
              autoComplete="off"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              placeholder={t("registerInvitePlaceholder")}
              className="px-3 py-2 rounded-lg bg-bg border border-border focus:border-accent focus:outline-none text-sm transition-colors"
              required
            />
          </label>
        )}

        {error && (
          <div className="text-xs text-red-500 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={
            submitting ||
            !username.trim() ||
            !password ||
            (isRegister && inviteRequired && !inviteCode.trim())
          }
          className="mt-1 px-4 py-2 rounded-lg bg-accent text-white font-semibold text-sm hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
        >
          {isRegister
            ? submitting
              ? t("registerSubmitting")
              : t("registerSubmit")
            : submitting
              ? t("loginSubmitting")
              : t("loginSubmit")}
        </button>

        <p className="text-[11px] text-text-3 leading-relaxed mt-1">
          {isRegister ? t("registerSwitchHint") : t("loginHint")}
        </p>
      </form>
    </div>
  );
}
