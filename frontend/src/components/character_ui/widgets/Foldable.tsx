/**
 * Click-to-fold section header used by both atom `section` and the
 * compound table renderers. Style matches the existing SectionTitle so
 * unfoldable / foldable blocks read the same.
 */
import { createContext, useContext, type ReactNode } from "react";
import { useFoldPref } from "../foldStore";

const CharacterUIContext = createContext<{ system: string }>({ system: "generic" });

export function CharacterUIProvider({
  system,
  children,
}: {
  system: string;
  children: ReactNode;
}) {
  return (
    <CharacterUIContext.Provider value={{ system }}>
      {children}
    </CharacterUIContext.Provider>
  );
}

export function useCharacterUISystem(): string {
  return useContext(CharacterUIContext).system;
}

interface Props {
  /** Stable id within the system — compound `key` field, or `section:<title>`. */
  nodeId: string;
  title: string;
  /** Item count shown next to the title (display only — no behaviour). */
  count?: number;
  children: ReactNode;
}

export function FoldableBlock({ nodeId, title, count, children }: Props) {
  const system = useCharacterUISystem();
  const { open, toggle } = useFoldPref(system, nodeId, true);
  return (
    <div>
      <button
        type="button"
        onClick={toggle}
        aria-expanded={open}
        className="flex items-center gap-1 w-full text-left mb-1.5 group"
      >
        <svg
          viewBox="0 0 24 24"
          className={[
            "h-3 w-3 shrink-0 text-text-3 transition-transform duration-150",
            open ? "rotate-90" : "",
          ].join(" ")}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M9 6l6 6-6 6" />
        </svg>
        <span className="text-[10px] font-semibold tracking-[0.08em] uppercase text-text-3 group-hover:text-text-2 transition-colors">
          {title}
        </span>
        {count != null && count > 0 && (
          <span className="text-[9px] text-text-3 ml-0.5 tabular-nums">
            ({count})
          </span>
        )}
      </button>
      {open && children}
    </div>
  );
}
