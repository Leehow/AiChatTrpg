/**
 * Recursive primitive renderer + barrel exports.
 *
 * Walks the LLM-compiled tree, dispatching on `node.type`. The tree is
 * data-only — no `dangerouslySetInnerHTML`, no eval. Every text value
 * passes through React's default text escaping.
 */

import type { ReactElement } from "react";
import type {
  BarPrimitive,
  CardPrimitive,
  CompoundPrimitive,
  GridPrimitive,
  ImagePrimitive,
  ListPrimitive,
  Primitive,
  SectionPrimitive,
  TagsPrimitive,
  TextPrimitive,
} from "./types";
import {
  type Card,
  type Scope,
  asArray,
  asNumber,
  asString,
  displayValue,
  iterateSource,
  resolveBarColor,
  resolveItemPath,
  resolvePath,
} from "./utils";
import { COMPOUND_TYPE_SET, renderCompound } from "./compounds";
import { FoldableBlock } from "./Foldable";

export * from "./types";
export * from "./utils";
export { CharacterUIProvider } from "./Foldable";

interface RenderCtx {
  card: Card;
  scope: Scope;
  /** When iterating a `list`, the scope is the entry and `itemKey`
   *  carries the array index or object key so `__key__` can resolve. */
  itemKey?: string;
}

function resolve(ctx: RenderCtx, path: string | null | undefined): unknown {
  if (ctx.itemKey !== undefined) {
    return resolveItemPath(ctx.scope, ctx.itemKey, path);
  }
  return resolvePath(ctx.scope, path);
}

// ---------- text ----------

const SIZE_CLS: Record<string, string> = {
  xs: "text-[10px]",
  sm: "text-[11px]",
  md: "text-sm",
  lg: "text-base font-semibold",
};
const EMPHASIS_CLS: Record<string, string> = {
  normal: "text-text",
  bold: "text-text font-semibold",
  muted: "text-text-2",
  accent: "text-accent",
};

// Heuristic: when label + value won't fit on one line in a narrow grid cell
// (~135 px wide), we'd rather stack them than let them overlap. CJK runs
// roughly 2x the visual width per char, so we count CJK chars as 2.
function visualWidth(s: string): number {
  let n = 0;
  for (const ch of s) {
    n += /[　-鿿＀-￯]/.test(ch) ? 2 : 1;
  }
  return n;
}

function TextNode({
  node,
  ctx,
}: {
  node: TextPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  let value: string;
  if (typeof node.text === "string" && node.text) {
    value = node.text;
  } else {
    value = displayValue(resolve(ctx, node.value_path));
  }
  const labelText = node.label_path
    ? displayValue(resolve(ctx, node.label_path))
    : node.label || "";
  if (!value && !labelText) return null;

  const sizeCls = SIZE_CLS[node.size || "md"] || SIZE_CLS.md;
  const empCls = EMPHASIS_CLS[node.emphasis || "normal"] || EMPHASIS_CLS.normal;
  // Auto-stack: when the label + value won't comfortably fit on a single
  // line of a narrow grid cell, drop to "label on top, value below" so we
  // don't get the chaotic mid-word wraps users see in 2-column identity
  // grids. The LLM's `inline: true` is treated as a hint, not a mandate.
  const explicitInline = !!node.inline;
  const tooLong = visualWidth(labelText) + visualWidth(value) > 18;
  const stack = !explicitInline || tooLong;

  if (!stack) {
    return (
      <span className={["inline-flex items-baseline gap-1 min-w-0", sizeCls].join(" ")}>
        {labelText && (
          <span className="text-text-3 text-[10px] shrink-0">{labelText}</span>
        )}
        {value && <span className={[empCls, "min-w-0 break-words"].join(" ")}>{value}</span>}
      </span>
    );
  }

  return (
    <div className={[sizeCls, "leading-snug min-w-0"].join(" ")}>
      {labelText && (
        <div className="text-text-3 text-[10px] font-semibold uppercase tracking-[0.06em] leading-tight">
          {labelText}
        </div>
      )}
      {value && (
        <div className={[empCls, "break-words"].join(" ")}>{value}</div>
      )}
    </div>
  );
}

// ---------- bar ----------

function BarNode({
  node,
  ctx,
}: {
  node: BarPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const cur = asNumber(resolve(ctx, node.current_path), 0);
  const max = asNumber(resolve(ctx, node.max_path), 0);
  const pct = max > 0 ? Math.min(100, (cur / max) * 100) : 0;
  const color = resolveBarColor(node.color);
  return (
    <div className="flex items-center gap-2 mb-1.5">
      <span className="text-[10px] font-semibold text-text-3 tracking-[0.06em] w-10 shrink-0 truncate">
        {node.label}
      </span>
      <div className="flex-1 h-1.5 bg-surface-2 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="text-[10px] font-mono text-text-2 tabular-nums w-12 text-right">
        {cur}/{max}
      </span>
    </div>
  );
}

// ---------- grid ----------

const GAP_CLS: Record<string, string> = {
  tight: "gap-0.5",
  normal: "gap-1.5",
  loose: "gap-2.5",
};

function GridNode({
  node,
  ctx,
}: {
  node: GridPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const cols = Math.max(1, Math.min(4, node.columns || 3));
  const colsCls = ["grid-cols-1", "grid-cols-2", "grid-cols-3", "grid-cols-4"][
    cols - 1
  ];
  const gapCls = GAP_CLS[node.gap || "normal"] || GAP_CLS.normal;
  const children = node.children || [];
  if (children.length === 0) return null;
  return (
    <div className={["grid", colsCls, gapCls].join(" ")}>
      {children.map((child, i) => (
        // `min-w-0` per cell so long content doesn't blow out the column
        // and overlap into neighbouring cells.
        <div key={i} className="min-w-0">
          <PrimitiveNode node={child} ctx={ctx} />
        </div>
      ))}
    </div>
  );
}

// ---------- section ----------

function SectionNode({
  node,
  ctx,
}: {
  node: SectionPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const children = node.children || [];
  if (children.length === 0) return null;
  const body = (
    <div className="space-y-1.5">
      {children.map((child, i) => (
        <PrimitiveNode key={i} node={child} ctx={ctx} />
      ))}
    </div>
  );
  if (!node.title) return body;
  return (
    <FoldableBlock nodeId={`section:${node.title}`} title={node.title}>
      {body}
    </FoldableBlock>
  );
}

// ---------- card ----------

function CardNode({
  node,
  ctx,
}: {
  node: CardPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const children = node.children || [];
  if (children.length === 0) return null;
  const tone = node.tone || "default";
  const cls =
    tone === "subtle"
      ? "bg-surface-2 rounded-lg px-1.5 py-1.5 text-center min-w-0"
      : "bg-surface border border-border rounded-lg px-2 py-1.5 min-w-0";
  return (
    <div className={cls}>
      {children.map((child, i) => (
        <PrimitiveNode key={i} node={child} ctx={ctx} />
      ))}
    </div>
  );
}

// ---------- image ----------

const ASPECT_CLS: Record<string, string> = {
  square: "aspect-square",
  portrait: "aspect-[3/4]",
  landscape: "aspect-video",
};

/** Tell a real image URL apart from a prose "portrait_reference" string the
 *  LLM template likes to emit (which happens to live at exactly the kind of
 *  field the compiler wires `src_path` to). Loading a Chinese description
 *  as `<img src>` would otherwise produce an ugly broken-image icon.
 */
function looksLikeImageUrl(s: string): boolean {
  if (!s) return false;
  if (/^(https?:|data:image\/|blob:)/i.test(s)) return true;
  if (s.startsWith("/")) return true;
  // Bare relative paths only count if they have a recognisable image extension.
  return /\.(png|jpe?g|gif|webp|svg|avif)(\?|#|$)/i.test(s);
}

function ImageNode({
  node,
  ctx,
}: {
  node: ImagePrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const rawSrc = asString(resolve(ctx, node.src_path), "");
  const src = looksLikeImageUrl(rawSrc) ? rawSrc : "";
  const alt = asString(resolve(ctx, node.alt_path), "character portrait");
  const aspectCls = ASPECT_CLS[node.aspect || "square"] || ASPECT_CLS.square;
  // Hide the placeholder entirely when we have no real image. A dashed
  // empty box for "portrait pending" was wasting a chunk of the panel
  // for every PC whose image gen hadn't run.
  if (!src) return null;
  // Render as a small inline-right portrait (chatlab-style): ~120px wide,
  // float-right so identity text wraps around it. The whole panel is
  // only ~270 px wide, so a full-width image dominates the section and
  // leaves identity prose squeezed underneath.
  return (
    <div
      className={[
        "float-right ml-2 mb-1 w-[110px] max-w-[40%]",
        "bg-surface-2 rounded-lg overflow-hidden border border-border",
        aspectCls,
      ].join(" ")}
    >
      <img
        src={src}
        alt={alt}
        className="w-full h-full object-cover"
        loading="lazy"
      />
    </div>
  );
}

// ---------- tags ----------

function TagsNode({
  node,
  ctx,
}: {
  node: TagsPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const tags = asArray(resolve(ctx, node.source_path))
    .map((t) => asString(t, ""))
    .filter(Boolean);
  if (tags.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag, i) => (
        <span
          key={`${tag}-${i}`}
          className="text-[10px] bg-accent-dim text-[var(--accent-text)] rounded-full px-2 py-0.5 font-medium"
        >
          {tag}
        </span>
      ))}
    </div>
  );
}

// ---------- list ----------

function ListNode({
  node,
  ctx,
}: {
  node: ListPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const source = resolve(ctx, node.source_path);
  let entries = iterateSource(source);
  if (entries.length === 0) {
    if (node.empty_text) {
      return (
        <div className="text-[11px] text-text-3 italic">{node.empty_text}</div>
      );
    }
    return null;
  }

  if (node.sort_by) {
    const order = node.sort_order === "desc" ? -1 : 1;
    const sortKey = node.sort_by;
    entries = [...entries].sort((a, b) => {
      const av = asString(resolveItemPath(a.item, a.key, sortKey), "");
      const bv = asString(resolveItemPath(b.item, b.key, sortKey), "");
      return av.localeCompare(bv) * order;
    });
  }

  const groups = new Map<string, typeof entries>();
  if (node.group_by) {
    const gkey = node.group_by;
    for (const e of entries) {
      const g =
        asString(resolveItemPath(e.item, e.key, gkey), "Other") || "Other";
      const list = groups.get(g) || [];
      list.push(e);
      groups.set(g, list);
    }
  } else {
    groups.set("", entries);
  }

  return (
    <div className="space-y-1.5">
      {Array.from(groups.entries()).map(([groupName, items]) => (
        <div key={groupName || "_"}>
          {groupName && node.group_by && (
            <div className="text-[10px] font-semibold text-text-3 uppercase tracking-[0.06em] mb-0.5">
              {groupName}
            </div>
          )}
          <div className="space-y-0.5">
            {items.map((entry) => (
              <PrimitiveNode
                key={entry.key}
                node={node.item_template}
                ctx={{ card: ctx.card, scope: entry.item, itemKey: entry.key }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------- dispatch ----------

export function PrimitiveNode({
  node,
  ctx,
}: {
  node: Primitive;
  ctx: RenderCtx;
}): ReactElement | null {
  // Compounds dispatch to their own module — they're leaf renderers and
  // don't recurse, so this avoids any cycle with the atom dispatch below.
  if (COMPOUND_TYPE_SET.has(node.type)) {
    return renderCompound(node as CompoundPrimitive, ctx);
  }
  switch (node.type) {
    case "section":
      return <SectionNode node={node} ctx={ctx} />;
    case "text":
      return <TextNode node={node} ctx={ctx} />;
    case "bar":
      return <BarNode node={node} ctx={ctx} />;
    case "grid":
      return <GridNode node={node} ctx={ctx} />;
    case "list":
      return <ListNode node={node} ctx={ctx} />;
    case "card":
      return <CardNode node={node} ctx={ctx} />;
    case "image":
      return <ImageNode node={node} ctx={ctx} />;
    case "tags":
      return <TagsNode node={node} ctx={ctx} />;
    default:
      return null;
  }
}

export function renderPrimitiveTree(
  tree: Primitive,
  card: Card,
): ReactElement | null {
  return <PrimitiveNode node={tree} ctx={{ card, scope: card }} />;
}
