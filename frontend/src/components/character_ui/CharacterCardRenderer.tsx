/**
 * Schema-driven character card renderer. Walks the LLM-compiled
 * primitive tree and renders it. The container is left untouched
 * (no PanelSection, no fixed width) so callers can drop this anywhere.
 *
 * Inside, the tree adapts to its host width via CSS container queries
 * (the @container utility on the wrapper).
 */

import type { Card, CharacterUISchema } from "./widgets";
import { CharacterUIProvider, renderPrimitiveTree } from "./widgets";

interface Props {
  schema: CharacterUISchema;
  card: Card;
  className?: string;
}

export function CharacterCardRenderer({ schema, card, className }: Props) {
  const tree = schema?.tree;
  if (!tree || !tree.type) {
    return (
      <div className="text-[11px] text-text-3 italic">
        Character schema is empty.
      </div>
    );
  }
  return (
    <CharacterUIProvider system={schema.system || "generic"}>
      <div
        className={["@container space-y-2", className].filter(Boolean).join(" ")}
      >
        {renderPrimitiveTree(tree, card)}
      </div>
    </CharacterUIProvider>
  );
}
