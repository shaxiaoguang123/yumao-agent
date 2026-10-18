import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const stylesheetPath = resolve(dirname(fileURLToPath(import.meta.url)), 'design-system.css');
const css = readFileSync(stylesheetPath, 'utf8');

describe('shipped layout contract', () => {
  it('uses one content width, 8px spacing, one control height, and a stacking breakpoint', () => {
    const widths = [...css.matchAll(/--content-max-width:\s*([^;]+);/g)].map((match) => match[1].trim());
    expect(widths).toEqual(['1120px']);

    const pagePadding = Number(css.match(/--page-padding:\s*(\d+)px/)?.[1]);
    const cardGap = Number(css.match(/--card-gap:\s*(\d+)px/)?.[1]);
    expect(pagePadding % 8).toBe(0);
    expect(cardGap % 8).toBe(0);
    expect(css).toContain('padding:var(--page-padding)');
    expect(css).toContain('gap:var(--card-gap)');

    const controlHeights = [...css.matchAll(/--control-height:\s*([^;]+);/g)].map((match) => match[1].trim());
    expect(controlHeights).toEqual(['40px']);
    expect(css).toContain('min-height:var(--control-height)');

    expect(css).toMatch(/@media\s*\(\s*max-width:\s*800px\s*\)[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  });
});
