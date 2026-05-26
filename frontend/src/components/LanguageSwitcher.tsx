import { useI18n } from "../i18n";
import { LOCALE_META } from "../i18n/messages";
import type { Locale } from "../i18n";

// Options are derived from `LOCALE_META` so adding a new locale to the
// i18n dict file (e.g. `ja: {...}` plus `LOCALE_META.ja`) automatically
// grows this switcher. Order = LOCALE_META declaration order.
const OPTIONS: { value: Locale; label: string }[] = (
  Object.entries(LOCALE_META) as Array<[Locale, { nativeLabel: string }]>
).map(([code, meta]) => ({ value: code, label: meta.nativeLabel }));

export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <div
      className={`inline-flex flex-wrap items-center gap-1 ${className}`}
      role="group"
      aria-label={t("language")}
    >
      {OPTIONS.map((opt) => {
        const active = opt.value === locale;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => setLocale(opt.value)}
            className={`px-2 py-0.5 rounded text-xs font-medium transition ${
              active
                ? "bg-accent text-white"
                : "bg-surface-2 text-text-3 hover:text-text hover:bg-border"
            }`}
            aria-pressed={active}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
