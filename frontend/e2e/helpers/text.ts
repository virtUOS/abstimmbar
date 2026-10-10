/** Text-level layout checks for the phone specs (#179): overlapping text,
 *  words broken across lines, text clipped inside its box, and floating
 *  overlays covering interactive content. Pure DOM, no dependencies. */
import { expect, type Locator, type Page } from '@playwright/test';

const r = (n: number) => Math.round(n);

/** No two text runs inside `scope` paint over each other (e.g. a long label
 *  running over its count, a chart marker over the question text). */
export async function expectNoTextOverlap(page: Page, scope: string, label = scope): Promise<void> {
  const { hits, textRuns } = await page.evaluate((scopeSel) => {
    const roots = Array.from(document.querySelectorAll(scopeSel));
    type Box = { text: string; owner: string; x1: number; y1: number; x2: number; y2: number; node: Text };
    const boxes: Box[] = [];
    const ownerOf = (el: Element | null) => {
      if (!el) return '?';
      const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0, 3).join('.') : '';
      return `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls ? '.' + cls : ''}`;
    };
    for (const root of roots) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
        if (!n.data.trim()) continue;
        const parent = n.parentElement;
        if (!parent) continue;
        const style = getComputedStyle(parent);
        if (style.visibility === 'hidden' || style.opacity === '0') continue;
        const range = document.createRange();
        range.selectNodeContents(n);
        for (const rect of Array.from(range.getClientRects())) {
          if (rect.width < 2 || rect.height < 2) continue;
          boxes.push({ text: n.data.trim().slice(0, 40), owner: ownerOf(parent), x1: rect.left, y1: rect.top, x2: rect.right, y2: rect.bottom, node: n });
        }
      }
    }
    const out: string[] = [];
    // One report per text run (a long label typically hits every token of the
    // neighbouring count).
    const reported = new Set<Text>();
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i];
        const b = boxes[j];
        if (a.node === b.node || reported.has(a.node) || reported.has(b.node)) continue;
        const w = Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1);
        const h = Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1);
        // Ignore hairline touches between adjacent lines/inline runs.
        if (w > 2 && h > 3) {
          reported.add(a.node);
          reported.add(b.node);
          out.push(
            `"${a.text}" (${a.owner}, x ${Math.round(a.x1)}–${Math.round(a.x2)}, y ${Math.round(a.y1)}–${Math.round(a.y2)}) overlaps ` +
              `"${b.text}" (${b.owner}, x ${Math.round(b.x1)}–${Math.round(b.x2)}, y ${Math.round(b.y1)}–${Math.round(b.y2)})`,
          );
        }
      }
    }
    return { hits: out, textRuns: boxes.length };
  }, scope);
  // Guard against a vacuous pass (wrong scope selector, nothing rendered yet).
  expect(textRuns, `${label}: no visible text found in "${scope}"`).toBeGreaterThan(0);
  expect(hits, `Overlapping text in ${label}:\n  • ${hits.slice(0, 10).join('\n  • ')}`).toEqual([]);
}

/** No whitespace-separated word inside the matched elements is split across
 *  two lines (e.g. "Live-/Umfrage", "Archivierte/Räume" in segmented controls). */
export async function expectNoMidWordBreaks(
  locator: Locator,
  label: string,
  minCount = 1,
): Promise<void> {
  const count = await locator.count();
  expect(count, `${label}: expected at least ${minCount} matching element(s), found ${count}`).toBeGreaterThanOrEqual(minCount);
  const broken = await locator.evaluateAll((els) => {
    const out: string[] = [];
    for (const el of els) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
        const re = /\S+/g;
        for (let m = re.exec(n.data); m; m = re.exec(n.data)) {
          const range = document.createRange();
          range.setStart(n, m.index);
          range.setEnd(n, m.index + m[0].length);
          const tops = new Set(
            Array.from(range.getClientRects())
              .filter((q) => q.width > 0)
              .map((q) => Math.round(q.top)),
          );
          if (tops.size > 1) {
            out.push(`"${m[0]}" in "${(el as HTMLElement).innerText.replace(/\s+/g, ' ').trim()}" spans ${tops.size} lines (box ${Math.round(rect.width)}×${Math.round(rect.height)} at x=${Math.round(rect.left)})`);
          }
        }
      }
    }
    return out;
  });
  expect(broken, `Words broken across lines in ${label}:\n  • ${broken.join('\n  • ')}`).toEqual([]);
}

/** Matched elements don't clip their own content horizontally
 *  (scrollWidth > clientWidth, e.g. "Sehr zufrieden" → "zufrieder"). */
export async function expectNoClippedContent(
  locator: Locator,
  label: string,
  minCount = 1,
): Promise<void> {
  const count = await locator.count();
  expect(count, `${label}: expected at least ${minCount} matching element(s), found ${count}`).toBeGreaterThanOrEqual(minCount);
  const clipped = await locator.evaluateAll((els) =>
    els
      .filter((el) => el.scrollWidth > el.clientWidth + 1)
      .map(
        (el) =>
          `"${(el as HTMLElement).innerText.replace(/\s+/g, ' ').trim()}" needs ${el.scrollWidth}px but has ${el.clientWidth}px`,
      ),
  );
  expect(clipped, `Clipped content in ${label}:\n  • ${clipped.join('\n  • ')}`).toEqual([]);
}

/** Scroll the page top→bottom and check that the overlay never sits on top of
 *  a control or text block (hit-testing five points per element). */
export async function expectOverlayNotCovering(
  page: Page,
  overlay: Locator,
  label: string,
): Promise<void> {
  const handle = await overlay.elementHandle();
  if (!handle) throw new Error(`${label}: overlay not found`);
  const covered = await page.evaluate(async (ov) => {
    const frame = () => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));
    const scroller = document.scrollingElement ?? document.documentElement;
    const seen = new Map<Element, string>();
    const max = scroller.scrollHeight - window.innerHeight;
    for (let y = 0; y <= Math.max(0, max) + 1; y += 100) {
      window.scrollTo(0, Math.min(y, max));
      await frame();
      const controls = document.querySelectorAll(
        'button, a[href], input:not([type=hidden]), select, textarea, [contenteditable="true"], label, h1, h2, h3, p',
      );
      for (const el of Array.from(controls)) {
        if (ov.contains(el) || seen.has(el)) continue;
        const box = el.getBoundingClientRect();
        if (box.width < 2 || box.height < 2) continue;
        // Centre plus four points inset 25% from the edges.
        const points = [
          [0.5, 0.5],
          [0.25, 0.25],
          [0.75, 0.25],
          [0.25, 0.75],
          [0.75, 0.75],
        ].map(([fx, fy]) => [box.left + box.width * fx, box.top + box.height * fy]);
        for (const [px, py] of points) {
          if (px < 0 || py < 0 || px >= window.innerWidth || py >= window.innerHeight) continue;
          const top = document.elementFromPoint(px, py);
          if (!top || !ov.contains(top)) continue;
          const name = (el.getAttribute('aria-label') ?? (el as HTMLElement).innerText ?? '')
            .replace(/\s+/g, ' ')
            .trim()
            .slice(0, 40);
          const ovBox = ov.getBoundingClientRect();
          seen.set(
            el,
            `${el.tagName.toLowerCase()} "${name}" (point ${Math.round(px)},${Math.round(py)}) at scrollY=${Math.round(scroller.scrollTop)} under overlay x ${Math.round(ovBox.left)}–${Math.round(ovBox.right)}, y ${Math.round(ovBox.top)}–${Math.round(ovBox.bottom)}`,
          );
          break;
        }
      }
    }
    window.scrollTo(0, 0);
    return Array.from(seen.values());
  }, handle);
  expect(covered, `${label} covers controls while scrolling:\n  • ${covered.slice(0, 10).join('\n  • ')}`).toEqual([]);
}

/** `a` sits on a row of its own below `b` (no shared line). */
export async function expectBelow(a: Locator, b: Locator, label: string): Promise<void> {
  const [ba, bb] = [await a.boundingBox(), await b.boundingBox()];
  expect(ba && bb, `${label}: element missing`).toBeTruthy();
  expect(
    ba!.y >= bb!.y + bb!.height - 1,
    `${label}: top=${r(ba!.y)} (x ${r(ba!.x)}–${r(ba!.x + ba!.width)}) is not below the bottom ${r(bb!.y + bb!.height)} (x ${r(bb!.x)}–${r(bb!.x + bb!.width)})`,
  ).toBe(true);
}
