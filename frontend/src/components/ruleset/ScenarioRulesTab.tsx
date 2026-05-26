import { useState } from "react";
import { useI18n } from "../../i18n";
import type { V6RulePackage } from "../../lib/ruleset/types";

interface Props {
  scenarios: V6RulePackage[];
}

export function ScenarioRulesTab({ scenarios }: Props) {
  const { t } = useI18n();
  const [openId, setOpenId] = useState<string | null>(
    scenarios[0]?.package_id ?? null
  );

  if (scenarios.length === 0) {
    return (
      <div className="max-w-[860px] mx-auto px-6 py-12 text-center text-text-3 text-sm">
        {t("scenariosEmpty")}
      </div>
    );
  }

  return (
    <div className="max-w-[860px] mx-auto px-6 py-6 flex flex-col gap-2">
      {scenarios.map((pkg) => {
        const open = openId === pkg.package_id;
        return (
          <div
            key={pkg.package_id}
            className="bg-surface border border-border rounded-xl overflow-hidden"
          >
            <button
              type="button"
              onClick={() => setOpenId(open ? null : pkg.package_id)}
              className="w-full flex items-center px-4 py-3 gap-2 hover:bg-surface-2 transition-colors text-left"
            >
              <span className="text-text-3 text-xs">▣</span>
              <span className="font-semibold text-sm flex-1 truncate">
                {pkg.package_id}
              </span>
              <span className="text-[11px] text-text-3">
                {Math.round((pkg.content?.length || 0) / 1000)}k
              </span>
              <span
                className={[
                  "text-text-3 text-[10px] transition-transform",
                  open ? "rotate-180" : "",
                ].join(" ")}
              >
                ▼
              </span>
            </button>
            {open && (
              <div className="px-4 pb-4 border-t border-border">
                <pre className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-text-2 font-sans pt-3">
                  {pkg.content || (pkg.error ? `[error] ${pkg.error}` : "")}
                </pre>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
