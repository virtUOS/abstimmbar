// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Beamer mind map (stage 1): the shared tree as a two-sided map — root in
 * the centre, main branches alternating right/left (balanced by size), sub-
 * terms growing outwards, curved connectors in the main branch's colour.
 *
 * Split in two parts:
 *  - `layoutMindMap` — a pure function (tree + node box sizes → positions,
 *    connectors, bounds). No DOM, no React; readable and testable on its own.
 *  - `MindMap` — measures the node boxes with a canvas (no layout thrash: no
 *    DOM reads per node), renders absolutely positioned pills plus an SVG for
 *    the connectors, animates layout changes via CSS transitions, and offers
 *    zoom/pan (wheel, drag, + / − / 0, Shift+arrows) with auto-fit. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { Maximize2, Minus, Plus, X } from "lucide-react";
import { localizedText } from "@basicbar/ui";
import type { LiveMindmapNode } from "../api";
import { INK } from "./palette";
import { EASE, useReducedMotion } from "./motion";

// ---------------------------------------------------------------------------
// Pure layout
// ---------------------------------------------------------------------------

export type Side = 1 | -1; // 1 = right of the root, -1 = left
export interface BoxSize {
  w: number;
  h: number;
}
/** The (visible) tree the layout works on. */
export interface MindTreeNode {
  id: number;
  children: MindTreeNode[];
}
export interface PlacedNode {
  id: number;
  /** Centre of the box; the root sits at (0, 0). */
  x: number;
  y: number;
  w: number;
  h: number;
  /** 1 = main branch. */
  depth: number;
  /** Index of the main branch among `branches` (colour). */
  branch: number;
  side: Side;
}
export interface MindEdge {
  /** The child node's id (one edge per non-root node). */
  id: number;
  /** SVG path (cubic Bézier) from the parent's outer edge to the child. */
  d: string;
  depth: number;
  branch: number;
}
export interface MindLayout {
  root: BoxSize;
  nodes: PlacedNode[];
  edges: MindEdge[];
  sides: Map<number, Side>;
  bounds: { minX: number; maxX: number; minY: number; maxY: number };
}
export interface MindGaps {
  /** Horizontal gap root → main branches. */
  rootX: number;
  /** Horizontal gap parent → child below the main branches. */
  x: number;
  /** Vertical gap between neighbouring main-branch subtrees. */
  branchY: number;
  /** Vertical gap between siblings deeper down. */
  y: number;
}
export const MIND_GAPS: MindGaps = { rootX: 68, x: 40, branchY: 24, y: 10 };

/** Main branches to sides: alternating, balanced by subtree height (greedy in
 * branch order — the lighter side gets the next branch, ties go right).
 * A branch keeps the side it had (`prev`) so the map doesn't flip around as
 * it grows; only when the sides drift clearly apart (> 1.5× + 120 px) do
 * single branches move over — each time the one that evens the sides out
 * best — so as few branches as possible change sides. */
export function assignSides(
  branches: { id: number; weight: number }[],
  prev?: ReadonlyMap<number, Side>,
): Map<number, Side> {
  const greedy = () => {
    const out = new Map<number, Side>();
    let right = 0;
    let left = 0;
    for (const b of branches) {
      if (right <= left) {
        out.set(b.id, 1);
        right += b.weight;
      } else {
        out.set(b.id, -1);
        left += b.weight;
      }
    }
    return out;
  };
  if (!prev || prev.size === 0) return greedy();
  const out = new Map<number, Side>();
  let right = 0;
  let left = 0;
  for (const b of branches) {
    const side = prev.get(b.id) ?? (right <= left ? 1 : -1);
    out.set(b.id, side);
    if (side === 1) right += b.weight;
    else left += b.weight;
  }
  const weights = new Map(branches.map((b) => [b.id, b.weight]));
  for (let guard = 0; guard < branches.length; guard++) {
    const heavy: Side = right >= left ? 1 : -1;
    const hi = Math.max(right, left);
    const lo = Math.min(right, left);
    if (hi <= lo * 1.5 + 120) break;
    let best: number | null = null;
    let bestGap = hi - lo;
    out.forEach((side, id) => {
      if (side !== heavy) return;
      const gap = Math.abs(hi - lo - 2 * weights.get(id)!);
      if (gap < bestGap) {
        bestGap = gap;
        best = id;
      }
    });
    if (best === null) break;
    const w = weights.get(best)!;
    out.set(best, -heavy as Side);
    if (heavy === 1) {
      right -= w;
      left += w;
    } else {
      left -= w;
      right += w;
    }
  }
  return out;
}

interface Measured {
  node: MindTreeNode;
  size: BoxSize;
  /** Height of the horizontal band the subtree occupies. */
  band: number;
  kids: Measured[];
  kidsSpan: number;
}

/** Two-sided tidy tree. Every subtree owns a horizontal band (its height =
 * max(own box, children's bands + gaps)); bands of siblings never overlap and
 * children always sit further out than their parent's outer edge, so neither
 * boxes nor connectors can collide. `size(node, depth)` gives each box. */
export function layoutMindMap(
  root: BoxSize,
  branches: MindTreeNode[],
  size: (node: MindTreeNode, depth: number) => BoxSize,
  prevSides?: ReadonlyMap<number, Side>,
  gaps: MindGaps = MIND_GAPS,
): MindLayout {
  const measure = (node: MindTreeNode, depth: number): Measured => {
    const own = size(node, depth);
    const kids = node.children.map((c) => measure(c, depth + 1));
    const kidsSpan =
      kids.reduce((sum, k) => sum + k.band, 0) + Math.max(0, kids.length - 1) * gaps.y;
    return { node, size: own, band: Math.max(own.h, kidsSpan), kids, kidsSpan };
  };
  const measured = branches.map((b) => measure(b, 1));
  const sides = assignSides(
    measured.map((m) => ({ id: m.node.id, weight: m.band })),
    prevSides,
  );

  const nodes: PlacedNode[] = [];
  const edges: MindEdge[] = [];
  let minX = -root.w / 2;
  let maxX = root.w / 2;
  let minY = -root.h / 2;
  let maxY = root.h / 2;

  const curve = (ax: number, ay: number, bx: number, by: number) => {
    const k = Math.abs(bx - ax) * 0.55;
    const s = Math.sign(bx - ax) || 1;
    const f = (v: number) => Math.round(v * 10) / 10;
    return `M ${f(ax)} ${f(ay)} C ${f(ax + s * k)} ${f(ay)} ${f(bx - s * k)} ${f(by)} ${f(bx)} ${f(by)}`;
  };

  // `inner` = distance of the box's inner edge from the root's centre line.
  const place = (
    m: Measured,
    depth: number,
    branch: number,
    side: Side,
    inner: number,
    top: number,
    anchor: { x: number; y: number },
  ) => {
    const { w, h } = m.size;
    const cy = top + m.band / 2;
    const cx = side * (inner + w / 2);
    nodes.push({ id: m.node.id, x: cx, y: cy, w, h, depth, branch, side });
    edges.push({ id: m.node.id, d: curve(anchor.x, anchor.y, side * inner, cy), depth, branch });
    minX = Math.min(minX, cx - w / 2);
    maxX = Math.max(maxX, cx + w / 2);
    minY = Math.min(minY, cy - h / 2);
    maxY = Math.max(maxY, cy + h / 2);
    let kidTop = cy - m.kidsSpan / 2;
    const outer = inner + w;
    for (const k of m.kids) {
      place(k, depth + 1, branch, side, outer + gaps.x, kidTop, { x: side * outer, y: cy });
      kidTop += k.band + gaps.y;
    }
  };

  for (const side of [1, -1] as Side[]) {
    const list = measured
      .map((m, branch) => ({ m, branch }))
      .filter(({ m }) => sides.get(m.node.id) === side);
    const total =
      list.reduce((sum, { m }) => sum + m.band, 0) + Math.max(0, list.length - 1) * gaps.branchY;
    let top = -total / 2;
    for (const { m, branch } of list) {
      place(m, 1, branch, side, root.w / 2 + gaps.rootX, top, { x: (side * root.w) / 2, y: 0 });
      top += m.band + gaps.branchY;
    }
  }
  return { root, nodes, edges, sides, bounds: { minX, maxX, minY, maxY } };
}

/** Viewport transform that fits the map: the largest scale (≤ `maxScale`) at
 * which everything is visible while the root stays near the centre — it may
 * move off-centre by at most `maxOffset` of the viewport per axis, so a
 * lopsided map (one deep side) isn't shrunk for empty space on the other.
 * Returns the scale and the root's position in the viewport. */
export function fitTransform(
  b: MindLayout["bounds"],
  vw: number,
  vh: number,
  { pad = 28, maxScale = 1.3, maxOffset = 0.12 } = {},
): { s: number; x: number; y: number } {
  if (vw <= 0 || vh <= 0) return { s: 1, x: vw / 2, y: vh / 2 };
  const scaleFor = (lo: number, hi: number, size: number) => {
    const before = -lo + pad;
    const after = hi + pad;
    const limit = maxOffset * size;
    const s = size / (before + after);
    const offset = s * before - size / 2;
    if (Math.abs(offset) <= limit) return s;
    const o = Math.sign(offset) * limit;
    return Math.min((size / 2 + o) / before, (size / 2 - o) / after);
  };
  const s = Math.min(scaleFor(b.minX, b.maxX, vw), scaleFor(b.minY, b.maxY, vh), maxScale);
  const rootAt = (lo: number, hi: number, size: number) => {
    const low = s * (-lo + pad) - size / 2; // smallest offset that shows the start
    const high = size / 2 - s * (hi + pad); // largest offset that shows the end
    const limit = maxOffset * size;
    const o = Math.min(Math.max(0, low), high); // as central as possible
    return size / 2 + Math.max(-limit, Math.min(limit, o));
  };
  return { s, x: rootAt(b.minX, b.maxX, vw), y: rootAt(b.minY, b.maxY, vh) };
}

/** Display term of a node: seeded nodes carry both languages (`text_i18n`),
 * resolved to the UI language; `text` is the canonical fallback (and the
 * merge key — never use this for comparisons). */
export function mindmapNodeText(n: LiveMindmapNode): string {
  return (n.text_i18n && localizedText(n.text_i18n)) || n.text;
}

/** Display descriptions: the predefined (seeded) one, if present, is first
 * and resolved to the UI language. */
export function mindmapNodeDescriptions(n: LiveMindmapNode): string[] {
  if (!n.description_i18n || n.descriptions.length === 0) return n.descriptions;
  return [localizedText(n.description_i18n) || n.descriptions[0], ...n.descriptions.slice(1)];
}

/** The presenter payload carries hidden nodes; a hidden node hides its whole
 * subtree. */
export function visibleMindmap(nodes: LiveMindmapNode[]): LiveMindmapNode[] {
  return nodes
    .filter((n) => !n.hidden)
    .map((n) => ({ ...n, children: visibleMindmap(n.children) }));
}

/** Explicitly hidden nodes (for the restore drawer): path from the main
 * branch down, and how many terms hang below. */
export function hiddenMindmapNodes(
  nodes: LiveMindmapNode[],
  path: string[] = [],
): { id: number; text: string; path: string[]; below: number }[] {
  const size = (n: LiveMindmapNode): number =>
    n.children.reduce((sum, c) => sum + 1 + size(c), 0);
  return nodes.flatMap((n) => [
    ...(n.hidden ? [{ id: n.id, text: mindmapNodeText(n), path, below: size(n) }] : []),
    ...hiddenMindmapNodes(n.children, [...path, mindmapNodeText(n)]),
  ]);
}

// ---------------------------------------------------------------------------
// Text measurement (canvas) and node styling
// ---------------------------------------------------------------------------

let ctx: CanvasRenderingContext2D | null = null;
const widthCache = new Map<string, number>();
function textWidth(text: string, px: number, weight: number, family: string): number {
  const key = `${weight}|${px}|${family}|${text}`;
  const hit = widthCache.get(key);
  if (hit !== undefined) return hit;
  if (!ctx) ctx = document.createElement("canvas").getContext("2d");
  let w = text.length * px * 0.56; // fallback estimate (as the word cloud does)
  if (ctx) {
    ctx.font = `${weight} ${px}px ${family}`;
    w = ctx.measureText(text).width;
  }
  if (widthCache.size > 5000) widthCache.clear();
  widthCache.set(key, w);
  return w;
}

/** Greedy word wrap into at most `maxLines` lines (the last one ellipsised
 * when the text doesn't fit); words longer than a line are split. */
function wrapText(
  text: string,
  px: number,
  weight: number,
  family: string,
  maxW: number,
  maxLines: number,
): { lines: string[]; width: number } {
  const measure = (s: string) => textWidth(s, px, weight, family);
  const lines: string[] = [];
  let line = "";
  const pushWord = (word: string) => {
    const candidate = line ? `${line} ${word}` : word;
    if (measure(candidate) <= maxW) {
      line = candidate;
      return;
    }
    if (line) lines.push(line);
    line = "";
    // Split an overlong word by characters.
    let rest = word;
    while (measure(rest) > maxW && rest.length > 1) {
      let cut = rest.length - 1;
      while (cut > 1 && measure(rest.slice(0, cut)) > maxW) cut--;
      lines.push(rest.slice(0, cut));
      rest = rest.slice(cut);
    }
    line = rest;
  };
  for (const word of text.split(/\s+/).filter(Boolean)) pushWord(word);
  if (line) lines.push(line);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    let last = kept[maxLines - 1];
    while (last.length > 1 && measure(`${last}…`) > maxW) last = last.slice(0, -1);
    kept[maxLines - 1] = `${last.trimEnd()}…`;
    lines.splice(0, lines.length, ...kept);
  }
  return { lines, width: Math.max(0, ...lines.map(measure)) };
}

interface NodeLook {
  font: number;
  weight: number;
  padX: number;
  padY: number;
  maxW: number;
}
const LOOKS: NodeLook[] = [
  { font: 26, weight: 800, padX: 26, padY: 15, maxW: 340 }, // root
  { font: 21, weight: 650, padX: 16, padY: 8, maxW: 250 },
  { font: 18, weight: 600, padX: 13, padY: 6, maxW: 230 },
  { font: 16, weight: 500, padX: 11, padY: 5, maxW: 210 },
];
const LINE = 1.22;
const DESC_LINE = 1.28;
const BADGE_GAP = 8;

interface NodeBox extends BoxSize {
  lines: string[];
  font: number;
  weight: number;
  padX: number;
  padY: number;
  desc: string[];
  descFont: number;
  badge: number; // badge width (0 = none)
}

function boxFor(
  text: string,
  count: number,
  descriptions: string[],
  depth: number,
  emphasise: boolean,
  detailed: boolean,
  family: string,
): NodeBox {
  const look = LOOKS[Math.min(depth, LOOKS.length - 1)];
  // Duplicate emphasis: bigger and bolder the more people named the term.
  const boost = emphasise && count > 1 ? Math.min(count - 1, 5) : 0;
  const font = Math.round(look.font * (1 + 0.08 * boost));
  const weight = Math.min(800, look.weight + (boost > 0 ? 150 : 0));
  const title = wrapText(text, font, weight, family, look.maxW, 3);
  const badgeFont = Math.round(font * 0.68);
  const badge =
    count > 1 ? Math.ceil(textWidth(String(count), badgeFont, 700, family)) + 14 : 0;
  let desc: string[] = [];
  let descW = 0;
  const descFont = Math.max(13, Math.round(font * 0.78));
  if (detailed && descriptions.length > 0) {
    const all = descriptions.flatMap(
      (d) => wrapText(d, descFont, 400, family, Math.max(look.maxW, 200), 3).lines,
    );
    desc = all.slice(0, 3);
    if (all.length > 3) {
      let last = desc[2];
      while (last.length > 1 && textWidth(`${last}…`, descFont, 400, family) > look.maxW)
        last = last.slice(0, -1);
      desc[2] = `${last.trimEnd()}…`;
    }
    descW = Math.max(0, ...desc.map((l) => textWidth(l, descFont, 400, family)));
  }
  const titleW = title.width + (badge ? BADGE_GAP + badge : 0);
  const w = Math.ceil(Math.max(titleW, descW) + 2 * look.padX + 2);
  const h = Math.ceil(
    title.lines.length * font * LINE +
      (desc.length ? 4 + desc.length * descFont * DESC_LINE : 0) +
      2 * look.padY,
  );
  return {
    w,
    h,
    lines: title.lines,
    font,
    weight,
    padX: look.padX,
    padY: look.padY,
    desc,
    descFont,
    badge,
  };
}

/** Mind-map palette: the six category hues of `palette.ts` (same OKLCH
 * lightness/chroma) plus green and coral — only here, since a mind map has no
 * right/wrong reading (polls keep avoiding green and red). */
export const MINDMAP_HUES = [250, 60, 305, 220, 85, 335, 150, 25] as const;
const fill = (hue: number) => `oklch(0.80 0.095 ${hue})`;
const tint = (hue: number) => `oklch(0.92 0.04 ${hue})`;
const deep = (hue: number) => `oklch(0.62 0.11 ${hue})`;

/** Hue index per main branch. `clockwise` lists the branch ids in display
 * order (right side top → bottom, then left side bottom → top); `stable`
 * gives each branch's creation rank (id order, incl. hidden branches). Each
 * branch prefers `stable % n`; if that equals a neighbour's hue (the list
 * wraps around) it takes the first hue used by neither neighbour. */
export function branchHues(
  clockwise: number[],
  stable: ReadonlyMap<number, number>,
  n: number = MINDMAP_HUES.length,
): Map<number, number> {
  const out = new Map<number, number>();
  const pref = (id: number) => (stable.get(id) ?? 0) % n;
  clockwise.forEach((id, i) => {
    const want = pref(id);
    if (clockwise.length < 2) {
      out.set(id, want);
      return;
    }
    const prevId = clockwise[(i - 1 + clockwise.length) % clockwise.length];
    const nextId = clockwise[(i + 1) % clockwise.length];
    const prev = out.get(prevId) ?? pref(prevId);
    const next = out.get(nextId) ?? pref(nextId);
    let hue = want;
    if (hue === prev || hue === next) {
      for (let h = 0; h < n; h++) {
        if (h !== prev && h !== next) {
          hue = h;
          break;
        }
      }
    }
    out.set(id, hue);
  });
  return out;
}

/** Fill / border / connector per depth: the main branch's hue, lighter
 * outwards. */
function nodeColors(depth: number, hue: number) {
  if (depth <= 1) return { bg: fill(hue), border: "transparent" };
  if (depth === 2) return { bg: tint(hue), border: fill(hue) };
  if (depth === 3) return { bg: `oklch(0.96 0.02 ${hue})`, border: `oklch(0.86 0.06 ${hue})` };
  return { bg: "#fff", border: `oklch(0.9 0.04 ${hue})` };
}
function edgeStyle(depth: number, hue: number) {
  if (depth <= 1) return { stroke: fill(hue), width: 6 };
  if (depth === 2) return { stroke: fill(hue), width: 4 };
  if (depth === 3) return { stroke: `oklch(0.85 0.07 ${hue})`, width: 3 };
  return { stroke: `oklch(0.88 0.05 ${hue})`, width: 2.5 };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const MIN_ZOOM = 0.15;
const MAX_ZOOM = 4;
const MAX_FIT = 1.3;
const FIT_PAD = 28;
const TRANSITION_MS = 600;

/** Side assignments survive a remount (e.g. the brief "closed" phase between
 * open and results, or navigating back to the question), keyed by
 * `memoryKey`. Small LRU. */
const sideMemory = new Map<string, Map<number, Side>>();

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.tagName !== "string") return false;
  if (el.tagName === "INPUT") {
    const type = (el as HTMLInputElement).type;
    return !["checkbox", "radio", "button", "submit", "range"].includes(type);
  }
  return el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable;
}

export default function MindMap({
  rootLabel,
  nodes: allNodes,
  detailed = false,
  highlightDuplicates = true,
  onHide,
  keyboard = true,
  memoryKey,
}: {
  rootLabel: string;
  /** Presenter-form tree (hidden nodes are skipped with their subtree). */
  nodes: LiveMindmapNode[];
  /** Show descriptions under the terms. */
  detailed?: boolean;
  highlightDuplicates?: boolean;
  /** Expert mode: × on hover hides a term with its subtree. */
  onHide?: (node: LiveMindmapNode) => void;
  /** Zoom/pan keys (+ / − / 0 / F, Shift+arrows) on the window. */
  keyboard?: boolean;
  /** Identifies the map (run + question) so the branch sides are kept. */
  memoryKey?: string;
}) {
  const { t, i18n } = useTranslation();
  // Seeded terms resolve to the UI language (mindmapNodeText): re-measure on
  // a language switch.
  const uiLang = i18n.resolvedLanguage;
  const reduced = useReducedMotion();
  const animate = !reduced;
  const containerRef = useRef<HTMLDivElement | null>(null);

  // --- font (for canvas measurement); re-measure once web fonts are in ---
  const [family, setFamily] = useState(
    () =>
      (typeof document !== "undefined" && getComputedStyle(document.body).fontFamily) ||
      "sans-serif",
  );
  const [fontTick, setFontTick] = useState(0);
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (el) setFamily(getComputedStyle(el).fontFamily || "sans-serif");
    let alive = true;
    document.fonts?.ready.then(() => {
      if (!alive) return;
      widthCache.clear();
      setFontTick((n) => n + 1);
    });
    return () => {
      alive = false;
    };
  }, []);

  // --- layout ---
  const visible = useMemo(() => visibleMindmap(allNodes), [allNodes]);
  const byId = useMemo(() => {
    const map = new Map<number, LiveMindmapNode>();
    const walk = (list: LiveMindmapNode[]) =>
      list.forEach((n) => {
        map.set(n.id, n);
        walk(n.children);
      });
    walk(visible);
    return map;
  }, [visible]);
  // Same term under several parents: a dashed ring marks each of them.
  const repeatedKeys = useMemo(() => {
    const seen = new Map<string, number>();
    byId.forEach((n) => {
      // `key` is presenter-only; results trees fall back to the lowercased text.
      const k = n.key ?? n.text.toLowerCase();
      seen.set(k, (seen.get(k) ?? 0) + 1);
    });
    return new Set([...seen].filter(([, c]) => c > 1).map(([k]) => k));
  }, [byId]);

  const sidesRef = useRef<Map<number, Side>>(
    (memoryKey && sideMemory.get(memoryKey)) || new Map(),
  );
  const { layout, boxes, rootBox } = useMemo(() => {
    const boxes = new Map<number, NodeBox>();
    const rootBox = boxFor(rootLabel || "…", 0, [], 0, false, false, family);
    const layout = layoutMindMap(
      rootBox,
      visible,
      (node, depth) => {
        const n = node as LiveMindmapNode;
        const box = boxFor(
          mindmapNodeText(n),
          n.count,
          mindmapNodeDescriptions(n),
          depth,
          highlightDuplicates,
          detailed,
          family,
        );
        boxes.set(n.id, box);
        return box;
      },
      sidesRef.current,
    );
    return { layout, boxes, rootBox };
    // fontTick: re-measure after web fonts have loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, rootLabel, detailed, highlightDuplicates, family, fontTick, uiLang]);
  // Hue per main branch (indexed like `PlacedNode.branch`): stable rank by
  // id over the full tree (hidden branches keep their rank), neighbours in
  // clockwise display order never share a hue.
  const branchHue = useMemo(() => {
    const stable = new Map(
      [...allNodes].map((n) => n.id).sort((a, b) => a - b).map((id, i) => [id, i] as const),
    );
    const mains = layout.nodes.filter((p) => p.depth === 1);
    const clockwise = [
      ...mains.filter((p) => p.side === 1).sort((a, b) => a.y - b.y),
      ...mains.filter((p) => p.side === -1).sort((a, b) => b.y - a.y),
    ].map((p) => p.id);
    const hues = branchHues(clockwise, stable);
    return visible.map((v) => MINDMAP_HUES[hues.get(v.id) ?? 0]);
  }, [layout, allNodes, visible]);
  useEffect(() => {
    sidesRef.current = layout.sides;
    if (!memoryKey) return;
    sideMemory.delete(memoryKey);
    sideMemory.set(memoryKey, layout.sides);
    if (sideMemory.size > 20) sideMemory.delete(sideMemory.keys().next().value!);
  }, [layout, memoryKey]);

  // --- fresh nodes pop in (kept for the animation's duration, so live
  // re-renders in between don't cut it short) ---
  const seenRef = useRef<Set<number> | null>(null);
  const freshRef = useRef<Map<number, number>>(new Map());
  const now = Date.now();
  if (seenRef.current === null) {
    seenRef.current = new Set(byId.keys()); // first paint: no pops
  } else if (animate) {
    byId.forEach((_, id) => {
      if (!seenRef.current!.has(id)) freshRef.current.set(id, now + 700);
    });
  }
  useEffect(() => {
    byId.forEach((_, id) => seenRef.current!.add(id));
    freshRef.current.forEach((until, id) => {
      if (until < Date.now()) freshRef.current.delete(id);
    });
  });
  const isFresh = (id: number) => (freshRef.current.get(id) ?? 0) > now;

  // --- viewport: size, auto-fit, zoom/pan ---
  const [viewport, setViewport] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setViewport({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const [view, setView] = useState({ s: 1, x: 0, y: 0, smooth: false });
  const manual = useRef(false);
  const fitted = useRef(false);
  const { minX, maxX, minY, maxY } = layout.bounds;
  const fitView = useMemo(
    () =>
      fitTransform({ minX, maxX, minY, maxY }, viewport.w, viewport.h, {
        pad: FIT_PAD,
        maxScale: MAX_FIT,
      }),
    [minX, maxX, minY, maxY, viewport.w, viewport.h],
  );
  useLayoutEffect(() => {
    if (viewport.w === 0 || manual.current) return;
    setView({ ...fitView, smooth: fitted.current });
    fitted.current = true;
  }, [fitView, viewport.w]);

  const viewRef = useRef(view);
  viewRef.current = view;
  const zoomAt = (factor: number, px: number, py: number) => {
    const v = viewRef.current;
    const s = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.s * factor));
    manual.current = true;
    setView({ s, x: px - ((px - v.x) * s) / v.s, y: py - ((py - v.y) * s) / v.s, smooth: false });
  };
  const zoomCentre = (factor: number) => {
    manual.current = true;
    const v = viewRef.current;
    const s = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.s * factor));
    const px = viewport.w / 2;
    const py = viewport.h / 2;
    setView({ s, x: px - ((px - v.x) * s) / v.s, y: py - ((py - v.y) * s) / v.s, smooth: true });
  };
  const panBy = (dx: number, dy: number) => {
    manual.current = true;
    const v = viewRef.current;
    setView({ ...v, x: v.x + dx, y: v.y + dy, smooth: true });
  };
  const fit = () => {
    manual.current = false;
    setView({ ...fitView, smooth: true });
  };
  const fitRef = useRef(fit);
  fitRef.current = fit;
  const zoomCentreRef = useRef(zoomCentre);
  zoomCentreRef.current = zoomCentre;
  const panByRef = useRef(panBy);
  panByRef.current = panBy;

  const zoomAtRef = useRef(zoomAt);
  zoomAtRef.current = zoomAt;
  // Wheel zoom (native listener: React's wheel handler is passive).
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomAtRef.current(Math.exp(-delta * 0.0015), e.clientX - rect.left, e.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  // Drag to pan (on the background or a node; not on buttons).
  const drag = useRef<{ id: number; x: number; y: number; vx: number; vy: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as Element).closest("button")) return;
    const v = viewRef.current;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, vx: v.x, vy: v.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!dragging && Math.hypot(dx, dy) < 3) return;
    if (!dragging) setDragging(true);
    manual.current = true;
    setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy, smooth: false }));
  };
  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== e.pointerId) return;
    drag.current = null;
    setDragging(false);
  };

  // Keys: + / − zoom, 0 or F fit, Shift+arrows pan. Plain arrows stay the
  // presenter's question navigation.
  useEffect(() => {
    if (!keyboard) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
      const step = 90;
      let handled = true;
      if (e.key === "+" || e.key === "=") zoomCentreRef.current(1.25);
      else if (e.key === "-" || e.key === "_") zoomCentreRef.current(1 / 1.25);
      else if (e.key === "0" || e.key === "f" || e.key === "F") fitRef.current();
      else if (e.shiftKey && e.key === "ArrowLeft") panByRef.current(step, 0);
      else if (e.shiftKey && e.key === "ArrowRight") panByRef.current(-step, 0);
      else if (e.shiftKey && e.key === "ArrowUp") panByRef.current(0, step);
      else if (e.shiftKey && e.key === "ArrowDown") panByRef.current(0, -step);
      else handled = false;
      if (handled) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keyboard]);

  const move = animate ? `${TRANSITION_MS}ms ${EASE}` : null;
  const worldTransition = move && view.smooth && !dragging ? `transform ${move}` : undefined;

  const nodeEl = (p: PlacedNode) => {
    const n = byId.get(p.id);
    const box = boxes.get(p.id);
    if (!n || !box) return null;
    const hue = branchHue[p.branch] ?? MINDMAP_HUES[0];
    const colors = nodeColors(p.depth, hue);
    const repeated = highlightDuplicates && repeatedKeys.has(n.key ?? n.text.toLowerCase());
    const roundish = box.lines.length === 1 && box.desc.length === 0;
    return (
      <div
        key={p.id}
        className="absolute left-0 top-0"
        style={{
          width: box.w,
          height: box.h,
          transform: `translate(${p.x - box.w / 2}px, ${p.y - box.h / 2}px)`,
          transition: move ? `transform ${move}, width ${move}, height ${move}` : undefined,
        }}
      >
        <div
          className={`group relative h-full w-full hover:z-10 focus-within:z-10 focus:outline-none ${isFresh(p.id) ? "ab-pop" : ""}`}
          title={n.count > 1 ? `${n.count}×` : undefined}
          // With moderation the node takes focus (Tab), which reveals its ×.
          tabIndex={onHide ? 0 : undefined}
          style={{
            background: colors.bg,
            border: `2px solid ${colors.border}`,
            borderRadius: roundish ? 9999 : 14,
            color: INK,
            padding: `${box.padY - 2}px ${box.padX - 2}px`,
            fontSize: box.font,
            fontWeight: box.weight,
            lineHeight: LINE,
            outline: repeated ? `2px dashed ${deep(hue)}` : undefined,
            outlineOffset: repeated ? 2 : undefined,
            boxShadow: p.depth === 1 ? "0 2px 6px rgba(15,23,42,0.08)" : undefined,
            transition: move ? `font-size ${move}` : undefined,
          }}
        >
          <div className="flex items-center" style={{ gap: box.badge ? BADGE_GAP : 0 }}>
            <div className="min-w-0 flex-1">
              {box.lines.map((line, i) => (
                <div key={i} className="whitespace-nowrap">
                  {line}
                </div>
              ))}
            </div>
            {box.badge > 0 && (
              <span
                className="inline-flex shrink-0 items-center justify-center rounded-full bg-white/85 tabular-nums"
                style={{
                  minWidth: box.badge,
                  fontSize: Math.round(box.font * 0.68),
                  fontWeight: 700,
                  lineHeight: 1.45,
                  color: deep(hue),
                }}
              >
                {n.count}
              </span>
            )}
          </div>
          {box.desc.length > 0 && (
            <div
              className="text-slate-600"
              style={{ marginTop: 4, fontSize: box.descFont, fontWeight: 400, lineHeight: DESC_LINE }}
            >
              {box.desc.map((line, i) => (
                <div key={i} className="whitespace-nowrap">
                  {line}
                </div>
              ))}
            </div>
          )}
          {onHide && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                e.currentTarget.blur();
                onHide(n);
              }}
              className="absolute -right-2.5 -top-2.5 hidden h-6 w-6 items-center justify-center rounded-full border border-slate-300 bg-white text-slate-500 shadow-sm hover:bg-slate-100 hover:text-slate-800 group-focus-within:flex group-hover:flex"
              aria-label={t("Hide {{word}}", { word: mindmapNodeText(n) })}
              title={t("Hide {{word}}", { word: mindmapNodeText(n) })}
            >
              <X className="h-3.5 w-3.5" strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
    );
  };

  const ctl =
    "flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 hover:text-slate-900";
  return (
    <div
      ref={containerRef}
      className={`relative h-full w-full select-none overflow-hidden ${dragging ? "cursor-grabbing" : "cursor-grab"}`}
      style={{ touchAction: "none" }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      data-testid="mindmap"
    >
      <div
        className="absolute left-0 top-0"
        style={{
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.s})`,
          transformOrigin: "0 0",
          transition: worldTransition,
        }}
      >
        <svg className="absolute left-0 top-0 overflow-visible" width={1} height={1} aria-hidden>
          {layout.edges.map((e) => {
            const st = edgeStyle(e.depth, branchHue[e.branch] ?? MINDMAP_HUES[0]);
            return (
              <path
                key={e.id}
                d={e.d}
                fill="none"
                stroke={st.stroke}
                strokeWidth={st.width}
                strokeLinecap="round"
                className={isFresh(e.id) ? "ab-fade-in" : undefined}
                style={
                  {
                    // CSS `d` animates the connector along with its nodes
                    // (Chromium/Firefox; elsewhere it simply jumps).
                    d: `path("${e.d}")`,
                    transition: move ? `d ${move}` : undefined,
                  } as CSSProperties
                }
              />
            );
          })}
        </svg>
        {/* Root: clearly the centre. */}
        <div
          className="absolute left-0 top-0 flex flex-col items-center justify-center rounded-2xl text-center text-white shadow-lg"
          style={{
            width: rootBox.w,
            height: rootBox.h,
            transform: `translate(${-rootBox.w / 2}px, ${-rootBox.h / 2}px)`,
            transition: move ? `transform ${move}, width ${move}, height ${move}` : undefined,
            background: INK,
            fontSize: rootBox.font,
            fontWeight: rootBox.weight,
            lineHeight: LINE,
          }}
        >
          {rootBox.lines.map((line, i) => (
            <div key={i} className="whitespace-nowrap">
              {line}
            </div>
          ))}
        </div>
        {layout.nodes.map(nodeEl)}
      </div>
      {visible.length === 0 && (
        <p
          className="pointer-events-none absolute inset-x-0 text-center text-lg text-slate-400"
          style={{ top: `calc(50% + ${(rootBox.h / 2) * view.s + 24}px)` }}
        >
          {t("No terms yet …")}
        </p>
      )}
      {/* Zoom controls (bottom right; the presenter's keys stay untouched). */}
      <div className="absolute bottom-2 right-2 flex flex-col rounded-xl border border-slate-200 bg-white/90 p-0.5 shadow-sm backdrop-blur">
        <button
          type="button"
          className={ctl}
          onClick={(e) => {
            e.currentTarget.blur();
            zoomCentre(1.25);
          }}
          aria-label={t("Zoom in (+)")}
          title={t("Zoom in (+)")}
        >
          <Plus className="h-5 w-5" />
        </button>
        <button
          type="button"
          className={ctl}
          onClick={(e) => {
            e.currentTarget.blur();
            zoomCentre(1 / 1.25);
          }}
          aria-label={t("Zoom out (−)")}
          title={t("Zoom out (−)")}
        >
          <Minus className="h-5 w-5" />
        </button>
        <button
          type="button"
          className={ctl}
          onClick={(e) => {
            e.currentTarget.blur();
            fit();
          }}
          aria-label={t("Fit to screen (0)")}
          title={t("Fit to screen (0)")}
        >
          <Maximize2 className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
}
