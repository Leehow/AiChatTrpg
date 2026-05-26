/**
 * Compound primitive renderers — opinionated shortcuts that bake in
 * domain conventions for the common patterns (skill list, attribute grid,
 * weapons, features). The LLM is told to prefer these over hand-composing
 * the same shapes from atoms, because hand-composed lists tend to dump
 * every field as labels and produce visually noisy layouts.
 *
 * All compounds are leaf renderers (no recursion into other primitives),
 * so this module has no dependency cycle with `index.tsx`.
 */

import type { ReactElement } from "react";
import type {
  AttributeGridPrimitive,
  FeatureListPrimitive,
  SkillTablePrimitive,
  WeaponTablePrimitive,
} from "./types";
import {
  type Card,
  asArray,
  asObject,
  asString,
  displayValue,
  iterateSource,
  resolveItemPath,
  resolvePath,
} from "./utils";
import { FoldableBlock } from "./Foldable";

interface RenderCtx {
  card: Card;
  scope: unknown;
  itemKey?: string;
}

function resolve(ctx: RenderCtx, path: string | null | undefined): unknown {
  if (ctx.itemKey !== undefined) {
    return resolveItemPath(ctx.scope, ctx.itemKey, path);
  }
  return resolvePath(ctx.scope, path);
}

/** Plain title for compounds whose row count doesn't justify a fold UI
 *  (e.g. attributeGrid is always expanded). Kept identical to the
 *  pre-fold style so unfoldable + foldable blocks read the same. */
function PlainTitle({ title }: { title?: string }) {
  if (!title) return null;
  return (
    <div className="text-[10px] font-semibold tracking-[0.08em] uppercase text-text-3 mb-1.5">
      {title}
    </div>
  );
}

/** Wrap a compound's body in the foldable header when the schema names
 *  it. Compound types carry an explicit `key`; fall back to the title
 *  when older schemas lack it so persistence still works. */
function withFold(
  node: { key?: string; title?: string },
  prefix: string,
  count: number,
  body: ReactElement,
): ReactElement {
  if (!node.title) return body;
  const id = node.key || `${prefix}:${node.title}`;
  return (
    <FoldableBlock nodeId={id} title={node.title} count={count}>
      {body}
    </FoldableBlock>
  );
}

// ---------- attributeGrid ----------

const COLS_CLS = [
  "grid-cols-1",
  "grid-cols-2",
  "grid-cols-3",
  "grid-cols-4",
];

export function AttributeGridNode({
  node,
  ctx,
}: {
  node: AttributeGridPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const source = asObject(resolve(ctx, node.source_path));
  if (!source) return null;
  const entries = Object.entries(source);
  if (entries.length === 0) return null;
  const cols = Math.max(1, Math.min(4, node.columns || 3));
  const valueField = node.value_field || "value";
  const modField = node.modifier_field;

  return (
    <div>
      <PlainTitle title={node.title} />
      <div className={["grid gap-1.5", COLS_CLS[cols - 1]].join(" ")}>
        {entries.map(([name, raw]) => {
          let value: string;
          let modifier: string | undefined;
          if (typeof raw === "object" && raw !== null && !Array.isArray(raw)) {
            const obj = raw as Record<string, unknown>;
            // Try the configured value_field first, then walk the
            // canonical chain. Older templates compiled with
            // value_field="default" still render after the runtime
            // card writes `value`/`half`/`fifth` (mechanical seed).
            const v =
              obj[valueField] ??
              obj.value ??
              obj.current ??
              obj.full ??
              obj.default ??
              obj.score ??
              obj.base;
            value = v != null ? displayValue(v) : "—";
            if (modField) {
              const m = obj[modField];
              modifier = m != null ? String(m) : undefined;
            }
          } else {
            value = displayValue(raw);
          }
          return (
            <div
              key={name}
              className="bg-surface-2 rounded-lg px-1.5 py-1.5 text-center min-w-0"
            >
              <div className="text-[9px] text-text-3 font-semibold tracking-[0.06em] truncate uppercase">
                {name}
              </div>
              <div className="text-sm font-semibold mt-0.5 tabular-nums">
                {value}
              </div>
              {modifier && (
                <div className="text-[10px] text-accent mt-0.5 tabular-nums">
                  {modifier}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- skillTable ----------

interface SkillRow {
  name: string;
  value: string;
  category: string;
}

function normaliseSkillRows(
  source: unknown,
  nameField: string,
  valueField: string,
  categoryField: string | undefined,
): SkillRow[] {
  const rows: SkillRow[] = [];
  const arr = asArray(source);
  if (arr.length > 0) {
    for (const entry of arr) {
      const obj = asObject(entry);
      if (!obj) continue;
      const name = asString(obj[nameField] ?? obj.label, "");
      if (!name) continue;
      const v = obj[valueField];
      const value = v != null ? displayValue(v) : "—";
      const category = categoryField
        ? asString(obj[categoryField], "")
        : "";
      rows.push({ name, value, category });
    }
    return rows;
  }
  const obj = asObject(source);
  if (obj) {
    for (const [name, raw] of Object.entries(obj)) {
      const sub = asObject(raw);
      let value: string;
      let category = "";
      if (sub) {
        const v = sub[valueField] ?? sub.value ?? sub.score;
        value = v != null ? displayValue(v) : "—";
        if (categoryField) category = asString(sub[categoryField], "");
      } else {
        value = displayValue(raw);
      }
      rows.push({ name, value, category });
    }
  }
  return rows;
}

export function SkillTableNode({
  node,
  ctx,
}: {
  node: SkillTablePrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const rows = normaliseSkillRows(
    resolve(ctx, node.source_path),
    node.name_field || "name",
    node.value_field || "value",
    node.category_field,
  );
  if (rows.length === 0) return null;

  const useGroups = !!node.category_field && rows.some((r) => r.category);
  const groups = new Map<string, SkillRow[]>();
  for (const r of rows) {
    const k = useGroups ? r.category || "Other" : "";
    const list = groups.get(k) || [];
    list.push(r);
    groups.set(k, list);
  }
  // Sort each group alphabetically by name.
  for (const list of groups.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }

  const body = (
    <div className="space-y-1.5">
      {Array.from(groups.entries()).map(([groupName, list]) => (
        <div key={groupName || "_"}>
          {useGroups && groupName && (
            <div className="text-[10px] font-semibold text-text-3 uppercase tracking-[0.06em] mb-0.5">
              {groupName}
            </div>
          )}
          <div className="grid grid-cols-[1fr_auto] gap-x-2 gap-y-0.5 text-[11px]">
            {list.map((r, idx) => (
              <span key={`${r.name}-${idx}`} className="contents">
                <span className="text-text-2 truncate">{r.name}</span>
                <span className="font-mono text-text font-semibold tabular-nums">
                  {r.value}
                </span>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
  return withFold(node, "skillTable", rows.length, body);
}

// ---------- weaponTable ----------

export function WeaponTableNode({
  node,
  ctx,
}: {
  node: WeaponTablePrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const items = asArray(resolve(ctx, node.source_path))
    .map((e) => asObject(e))
    .filter((e): e is Record<string, unknown> => e !== null);
  if (items.length === 0) return null;
  const nameF = node.name_field || "name";
  const skillF = node.skill_field || "skill";
  const damageF = node.damage_field || "damage";

  const body = (
    <div className="space-y-0.5">
      {items.map((w, i) => {
        const name = asString(w[nameF], `Weapon ${i + 1}`);
        const skill = asString(w[skillF], "");
        const damage = asString(w[damageF], "");
        return (
          <div
            key={name + i}
            className="grid grid-cols-[1fr_auto] gap-x-2 text-[11px] items-baseline min-w-0"
          >
            <span className="text-text font-medium truncate">{name}</span>
            <span className="text-text-2 font-mono tabular-nums whitespace-nowrap">
              {damage || "—"}
            </span>
            {skill && (
              <span className="col-span-2 text-[10px] text-text-3 -mt-0.5">
                {skill}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
  return withFold(node, "weaponTable", items.length, body);
}

// ---------- featureList ----------

export function FeatureListNode({
  node,
  ctx,
}: {
  node: FeatureListPrimitive;
  ctx: RenderCtx;
}): ReactElement | null {
  const source = resolve(ctx, node.source_path);
  const items = iterateSource(source);
  if (items.length === 0) return null;
  const nameF = node.name_field || "name";
  const descF = node.description_field || "description";

  const body = (
    <div className="space-y-1.5">
      {items.map(({ key, item }) => {
        const obj = asObject(item);
        let name = "";
        let desc = "";
        if (obj) {
          name = asString(obj[nameF] ?? obj.label ?? key, key);
          desc = asString(
            obj[descF] ?? obj.effect ?? obj.text ?? obj.summary,
            "",
          );
        } else {
          name = key;
          desc = displayValue(item);
        }
        if (!name && !desc) return null;
        return (
          <div
            key={key}
            className="bg-surface-2 rounded-md px-2 py-1.5 min-w-0"
          >
            {name && (
              <div className="text-[12px] font-semibold text-text leading-tight">
                {name}
              </div>
            )}
            {desc && (
              <div className="text-[11px] text-text-2 leading-relaxed mt-0.5">
                {desc}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
  return withFold(node, "featureList", items.length, body);
}

// ---------- dispatch ----------

export type CompoundNode =
  | AttributeGridPrimitive
  | SkillTablePrimitive
  | WeaponTablePrimitive
  | FeatureListPrimitive;

export function renderCompound(
  node: CompoundNode,
  ctx: RenderCtx,
): ReactElement | null {
  switch (node.type) {
    case "attributeGrid":
      return <AttributeGridNode node={node} ctx={ctx} />;
    case "skillTable":
      return <SkillTableNode node={node} ctx={ctx} />;
    case "weaponTable":
      return <WeaponTableNode node={node} ctx={ctx} />;
    case "featureList":
      return <FeatureListNode node={node} ctx={ctx} />;
    default:
      return null;
  }
}

export const COMPOUND_TYPE_SET = new Set([
  "attributeGrid",
  "skillTable",
  "weaponTable",
  "featureList",
]);
