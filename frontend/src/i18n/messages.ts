import { en } from "./locales/en";
import { zh } from "./locales/zh";
import { ja } from "./locales/ja";
import { de } from "./locales/de";
import { fr } from "./locales/fr";
import { es } from "./locales/es";
import { ru } from "./locales/ru";

export type Locale = "en" | "zh" | "ja" | "de" | "fr" | "es" | "ru";
export type { MessageKey } from "./locales/en";

export const messages: Record<Locale, Record<string, string>> = {
  en,
  zh,
  ja,
  de,
  fr,
  es,
  ru,
};

/** Per-locale presentation metadata. Adding a new locale to this map plus
 *  a corresponding `messages` dict is the only thing the global language
 *  switcher (top-right toggle) needs to grow a new button. The order of
 *  entries here is also the order rendered in the switcher. */
export const LOCALE_META: Record<Locale, {
  /** Label shown in the toggle. Native script preferred. */
  nativeLabel: string;
}> = {
  en: { nativeLabel: "EN" },
  zh: { nativeLabel: "中文" },
  ja: { nativeLabel: "日本語" },
  de: { nativeLabel: "DE" },
  fr: { nativeLabel: "FR" },
  es: { nativeLabel: "ES" },
  ru: { nativeLabel: "RU" },
};
