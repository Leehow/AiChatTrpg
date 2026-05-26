import { useI18n } from "../../../i18n";

export function EmptyHint() {
  const { t } = useI18n();
  return (
    <div className="text-[11px] italic text-text-3 px-1 py-1">
      {t("debugMemoryEmpty")}
    </div>
  );
}
