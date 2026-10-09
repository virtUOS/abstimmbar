/** Layout assertions for the phone-width specs (#179).
 *
 *  The app shell clips horizontal overflow (`overflow-x: clip`), so a plain
 *  document scrollWidth check misses content that is cut off at the right
 *  edge. `expectNoHorizontalOverflow` therefore also walks every visible
 *  element and reports boxes that leave the viewport, unless they sit inside
 *  an intentional horizontal scroller (an ancestor with overflow-x auto/scroll). */
import { expect, type Locator, type Page } from '@playwright/test';

export type Offender = {
  selector: string;
  text: string;
  left: number;
  right: number;
  width: number;
};

export type OverflowReport = {
  innerWidth: number;
  scrollWidth: number;
  clientWidth: number;
  offenders: Offender[];
};

/** Collect overflow facts in the page (pure DOM, no dependencies). */
export async function measureHorizontalOverflow(page: Page): Promise<OverflowReport> {
  // Measure against the configured device width: mobile Chromium widens the
  // layout viewport (window.innerWidth) to fit overflowing content.
  const deviceWidth = page.viewportSize()?.width;
  return page.evaluate((configured) => {
    const vw = configured ?? window.innerWidth;
    const scroller = document.scrollingElement ?? document.documentElement;

    const describe = (el: Element): string => {
      const parts: string[] = [];
      let node: Element | null = el;
      // Short path: up to 3 levels, stop at the first id or data-tour anchor.
      for (let depth = 0; node && depth < 3; depth++) {
        let part = node.tagName.toLowerCase();
        if (node.id) part += `#${node.id}`;
        const tour = node.getAttribute('data-tour');
        if (tour) part += `[data-tour="${tour}"]`;
        const role = node.getAttribute('role');
        if (role) part += `[role="${role}"]`;
        const cls =
          typeof node.className === 'string'
            ? node.className.trim().split(/\s+/).filter(Boolean).slice(0, 4)
            : [];
        if (cls.length) part += `.${cls.join('.')}`;
        parts.unshift(part);
        if (node.id || tour) break;
        node = node.parentElement;
      }
      return parts.join(' > ');
    };

    const isVisible = (el: Element, rect: DOMRect): boolean => {
      // sr-only / hairline helpers are 1px boxes — not visible content.
      if (rect.width <= 1 || rect.height <= 1) return false;
      const style = getComputedStyle(el);
      if (style.visibility === 'hidden' || style.display === 'none') return false;
      if (Number(style.opacity) === 0) return false;
      // Clipped away completely (the sr-only pattern).
      if (style.clip === 'rect(0px, 0px, 0px, 0px)') return false;
      if (style.clipPath === 'inset(50%)') return false;
      return true;
    };

    /** Inside an element that scrolls horizontally on purpose? */
    const inScroller = (el: Element, includeSelf = false): boolean => {
      for (let a = includeSelf ? el : el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
        const ox = getComputedStyle(a).overflowX;
        if (ox === 'auto' || ox === 'scroll') return true;
      }
      return false;
    };

    const offendingSet = new Set<Element>();
    const hasOffendingAncestor = (el: Element): boolean => {
      for (let a = el.parentElement; a; a = a.parentElement) if (offendingSet.has(a)) return true;
      return false;
    };
    const offenders: Offender[] = [];
    for (const el of Array.from(document.body.querySelectorAll('*'))) {
      if (el instanceof SVGElement && !(el instanceof SVGSVGElement)) continue;
      const rect = el.getBoundingClientRect();
      if (!isVisible(el, rect)) continue;
      if (rect.right <= vw + 1 && rect.left >= -1) continue;
      if (inScroller(el)) continue;
      offendingSet.add(el);
      // Report the outermost offender only; its descendants follow it.
      if (hasOffendingAncestor(el)) continue;
      offenders.push({
        selector: describe(el),
        text: ((el as HTMLElement).innerText ?? el.textContent ?? '')
          .replace(/\s+/g, ' ')
          .trim()
          .slice(0, 60),
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      });
    }
    // Text that spills out of a box which itself fits (e.g. a long unbreakable
    // word inside a button) — invisible to the element-box pass above.
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const textParents = new Set<Element>();
    for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
      const parent = n.parentElement;
      if (!parent || !n.data.trim() || textParents.has(parent)) continue;
      if (offendingSet.has(parent) || hasOffendingAncestor(parent)) continue;
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE'].includes(parent.tagName)) continue;
      const pRect = parent.getBoundingClientRect();
      if (!isVisible(parent, pRect)) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      const rects = Array.from(range.getClientRects()).filter((q) => q.width > 0);
      const bad = rects.filter((q) => q.right > vw + 1 || q.left < -1);
      if (!bad.length || inScroller(parent, true)) continue;
      // Deliberate truncation (`truncate`, `line-clamp-*`) clips with an ellipsis.
      const ps = getComputedStyle(parent);
      if (ps.textOverflow === 'ellipsis' || (ps as any).webkitLineClamp > 0) continue;
      textParents.add(parent);
      offenders.push({
        selector: `${describe(parent)} (text)`,
        text: n.data.replace(/\s+/g, ' ').trim().slice(0, 60),
        left: Math.round(Math.min(...bad.map((q) => q.left))),
        right: Math.round(Math.max(...bad.map((q) => q.right))),
        width: Math.round(Math.max(...bad.map((q) => q.width))),
      });
    }
    return {
      innerWidth: vw,
      scrollWidth: scroller.scrollWidth,
      clientWidth: scroller.clientWidth,
      offenders,
    };
  }, deviceWidth);
}

export function formatOverflow(report: OverflowReport, max = 12): string {
  const lines = [
    `viewport ${report.innerWidth}px, document scrollWidth ${report.scrollWidth} / clientWidth ${report.clientWidth}`,
    ...report.offenders
      .slice(0, max)
      .map(
        (o) =>
          `  • ${o.selector}  "${o.text}"  left=${o.left} right=${o.right} width=${o.width}`,
      ),
  ];
  if (report.offenders.length > max) lines.push(`  … and ${report.offenders.length - max} more`);
  return lines.join('\n');
}

/** (a) the document doesn't scroll sideways, (b) no visible element leaves
 *  the viewport except inside an intentional horizontal scroller. */
export async function expectNoHorizontalOverflow(page: Page, label = page.url()): Promise<void> {
  const report = await measureHorizontalOverflow(page);
  const problems: string[] = [];
  if (report.scrollWidth > report.clientWidth) {
    problems.push(`document scrolls horizontally (scrollWidth ${report.scrollWidth} > clientWidth ${report.clientWidth})`);
  }
  if (report.offenders.length) {
    problems.push(`${report.offenders.length} element(s) outside 0…${report.innerWidth}px`);
  }
  expect(
    problems,
    `Horizontal overflow on ${label}: ${problems.join('; ')}\n${formatOverflow(report)}`,
  ).toEqual([]);
}

/** The element's box lies horizontally within the viewport and starts below
 *  its top edge (menus/popovers). */
export async function expectInViewport(locator: Locator, label = 'element'): Promise<void> {
  await expect(locator).toBeVisible();
  const box = await locator.boundingBox();
  const vw =
    locator.page().viewportSize()?.width ?? (await locator.page().evaluate(() => window.innerWidth));
  expect(box, `${label}: no bounding box`).not.toBeNull();
  const { x, y, width, height } = box!;
  const r = (n: number) => Math.round(n);
  expect(
    x >= -1 && x + width <= vw + 1 && y >= -1,
    `${label} leaves the viewport: left=${r(x)} right=${r(x + width)} top=${r(y)} ` +
      `(width ${r(width)}, height ${r(height)}; viewport width ${vw})`,
  ).toBe(true);
}
