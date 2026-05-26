import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { messages, LOCALE_META, type Locale, type MessageKey } from "./messages";

const STORAGE_KEY = "chatrpg.locale";

const SUPPORTED_LOCALES = Object.keys(LOCALE_META) as Locale[];

function isLocale(value: string | null): value is Locale {
  return value !== null && (SUPPORTED_LOCALES as string[]).includes(value);
}

// Map a navigator language tag (e.g. "fr-CA", "zh-Hant") to a supported
// locale by matching the prefix. Falls back to English when nothing
// matches so first-time visitors always get a usable UI.
function detectInitial(): Locale {
  if (typeof window === "undefined") return "en";
  const saved = window.localStorage.getItem(STORAGE_KEY);
  if (isLocale(saved)) return saved;
  const nav = (window.navigator.language || "").toLowerCase();
  for (const loc of SUPPORTED_LOCALES) {
    if (nav.startsWith(loc)) return loc;
  }
  return "en";
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(detectInitial);

  useEffect(() => {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : locale;
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    try {
      window.localStorage.setItem(STORAGE_KEY, l);
    } catch {
      // ignore
    }
  }, []);

  const t = useCallback(
    (key: MessageKey, vars?: Record<string, string | number>) => {
      const dict = messages[locale] ?? messages.en;
      let str = (dict[key] as string) ?? (messages.en[key] as string) ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          str = str.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
        }
      }
      return str;
    },
    [locale]
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside <I18nProvider>");
  return ctx;
}

export type { Locale, MessageKey };
