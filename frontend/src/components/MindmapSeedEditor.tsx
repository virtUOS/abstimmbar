// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Outline editor for a mindmap question's predefined branches (stage 1).
 * Mirrors the participant interaction model: an indented list below the
 * root, "+" adds a child term, × removes a term (with its sub-branches).
 * Terms are plain canonical-language text, max. 60 characters; levels count
 * from the root's children (1) down to the question's depth. */
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Plus, X } from "lucide-react";
import type { MindmapSeedNode } from "../api";
import { Button } from "./ui";

export const MINDMAP_TEXT_MAX = 60;
export const MINDMAP_DESCRIPTION_MAX = 200;
export const MINDMAP_SEED_MAX_NODES = 100;

/** Editor-side node: a stable client id for React keys and focus. */
export interface EditableSeedNode {
  id: number;
  text: string;
  description: string;
  children: EditableSeedNode[];
}

let nextSeedId = 1;

export function toEditableSeed(nodes: MindmapSeedNode[] | undefined): EditableSeedNode[] {
  return (nodes ?? []).map((node) => ({
    id: nextSeedId++,
    text: node.text ?? "",
    description: node.description ?? "",
    children: toEditableSeed(node.children),
  }));
}

function hasText(node: EditableSeedNode): boolean {
  return node.text.trim() !== "" || node.children.some(hasText);
}

/** API shape; blank rows without filled sub-branches are dropped (like a
 * blank trailing answer option). */
export function fromEditableSeed(nodes: EditableSeedNode[]): MindmapSeedNode[] {
  return nodes.filter(hasText).map((node) => ({
    text: node.text.trim().replace(/\s+/g, " "),
    description: node.description.trim(),
    children: fromEditableSeed(node.children),
  }));
}

export function countSeed(nodes: EditableSeedNode[]): number {
  return nodes.reduce((sum, node) => sum + 1 + countSeed(node.children), 0);
}

/** Deepest level used by filled terms (0 = no predefined branches). */
export function seedDepth(nodes: MindmapSeedNode[], level = 1): number {
  return nodes.reduce(
    (max, node) => Math.max(max, level, seedDepth(node.children, level + 1)),
    0,
  );
}

/** First client-side problem of a (serialized) seed, as an English source
 * string for t(), or null. Mirrors backend rooms/mindmap.clean_seed. */
export function seedProblem(
  nodes: MindmapSeedNode[],
  depth: number,
): { key: string; values?: Record<string, string> } | null {
  if (seedDepth(nodes) > depth) {
    return { key: "The predefined branches are deeper than the allowed depth." };
  }
  const walk = (list: MindmapSeedNode[]): { key: string; values?: Record<string, string> } | null => {
    const seen = new Set<string>();
    for (const node of list) {
      if (!node.text) return { key: "Every predefined branch needs a term." };
      const key = node.text.toLocaleLowerCase();
      if (seen.has(key)) {
        return { key: "“{{term}}” appears twice at the same place.", values: { term: node.text } };
      }
      seen.add(key);
      const inner = walk(node.children);
      if (inner) return inner;
    }
    return null;
  };
  return walk(nodes);
}

function mapTree(
  nodes: EditableSeedNode[],
  fn: (node: EditableSeedNode) => EditableSeedNode | null,
): EditableSeedNode[] {
  return nodes.flatMap((node) => {
    const next = fn(node);
    if (next === null) return [];
    return [{ ...next, children: mapTree(next.children, fn) }];
  });
}

export default function MindmapSeedEditor({
  value,
  onChange,
  depth,
  descriptions,
  rootLabel,
}: {
  value: EditableSeedNode[];
  onChange: (next: EditableSeedNode[]) => void;
  depth: number;
  descriptions: boolean;
  rootLabel: string;
}) {
  const { t } = useTranslation();
  const focusId = useRef<number | null>(null);
  const inputs = useRef(new Map<number, HTMLInputElement>());
  const full = countSeed(value) >= MINDMAP_SEED_MAX_NODES;

  // Focus a freshly added row once it is rendered.
  useEffect(() => {
    if (focusId.current == null) return;
    inputs.current.get(focusId.current)?.focus();
    focusId.current = null;
  });

  function newNode(): EditableSeedNode {
    const node = { id: nextSeedId++, text: "", description: "", children: [] };
    focusId.current = node.id;
    return node;
  }

  function update(id: number, patch: Partial<EditableSeedNode>) {
    onChange(mapTree(value, (node) => (node.id === id ? { ...node, ...patch } : node)));
  }

  function addChild(id: number) {
    if (full) return;
    onChange(
      mapTree(value, (node) =>
        node.id === id ? { ...node, children: [...node.children, newNode()] } : node,
      ),
    );
  }

  function addSiblingAfter(id: number) {
    if (full) return;
    const insert = (list: EditableSeedNode[]): EditableSeedNode[] => {
      const index = list.findIndex((node) => node.id === id);
      if (index >= 0) return [...list.slice(0, index + 1), newNode(), ...list.slice(index + 1)];
      return list.map((node) => ({ ...node, children: insert(node.children) }));
    };
    onChange(insert(value));
  }

  function remove(id: number) {
    onChange(mapTree(value, (node) => (node.id === id ? null : node)));
  }

  function renderRows(nodes: EditableSeedNode[], level: number) {
    return nodes.map((node) => (
      <li key={node.id}>
        <div className="flex items-start gap-1.5 py-1">
          <span
            aria-hidden
            className="mt-2.5 h-2 w-2 shrink-0 rounded-full bg-brand-400 dark:bg-brand-600"
            style={{ opacity: Math.max(0.35, 1 - (level - 1) * 0.15) }}
          />
          <div className="grid min-w-0 flex-1 gap-1">
            <input
              ref={(element) => {
                if (element) inputs.current.set(node.id, element);
                else inputs.current.delete(node.id);
              }}
              type="text"
              value={node.text}
              maxLength={MINDMAP_TEXT_MAX}
              placeholder={t("Term")}
              aria-label={t("Term (level {{level}})", { level })}
              onChange={(event) => update(node.id, { text: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addSiblingAfter(node.id);
                }
              }}
              className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
            {descriptions && (
              <input
                type="text"
                value={node.description}
                maxLength={MINDMAP_DESCRIPTION_MAX}
                placeholder={t("Description (optional)")}
                aria-label={t("Description (optional)")}
                onChange={(event) => update(node.id, { description: event.target.value })}
                className="w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
              />
            )}
          </div>
          {level < depth && (
            <Button
              variant="ghost"
              aria-label={t("Add sub-term")}
              title={t("Add sub-term")}
              disabled={full}
              onClick={() => addChild(node.id)}
            >
              <Plus aria-hidden className="h-4 w-4" />
            </Button>
          )}
          <Button
            variant="ghost"
            aria-label={t("Delete term")}
            title={
              node.children.length
                ? t("Delete term with its sub-terms")
                : t("Delete term")
            }
            onClick={() => remove(node.id)}
          >
            <X aria-hidden className="h-4 w-4" />
          </Button>
        </div>
        {node.children.length > 0 && (
          <ul className="ml-3 border-l border-slate-200 pl-3 dark:border-slate-700">
            {renderRows(node.children, level + 1)}
          </ul>
        )}
      </li>
    ));
  }

  return (
    <div>
      <div className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
        {/* "+" sits right behind the root, like behind every other term. */}
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <span className="inline-block rounded-full bg-brand-100 px-2.5 py-0.5 text-sm font-semibold text-brand-800 dark:bg-brand-950 dark:text-brand-200">
            {rootLabel || t("Root (question text)")}
          </span>
          <Button
            variant="ghost"
            aria-label={t("Add branch")}
            title={t("Add branch")}
            disabled={full}
            onClick={() => {
              if (!full) onChange([...value, newNode()]);
            }}
          >
            <Plus aria-hidden className="h-4 w-4" />
          </Button>
          {full && (
            <span className="text-xs text-slate-400">
              {t("At most {{max}} predefined terms.", { max: MINDMAP_SEED_MAX_NODES })}
            </span>
          )}
        </div>
        {value.length > 0 && (
          <ul className="ml-3 border-l border-slate-200 pl-3 dark:border-slate-700">
            {renderRows(value, 1)}
          </ul>
        )}
      </div>
    </div>
  );
}
