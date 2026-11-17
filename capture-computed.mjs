// capture-computed.mjs — 抓浏览器真实计算样式，供 compare.py 对账
//
// 约定：给需要核对的元素加 data-ds="图层名"（与 MasterGo 图层名保持一致最好，
// 或者在 compare.py 里靠模糊匹配）。没有 data-ds 时退化为按选择器清单抓。
//
// 用法：
//   node capture-computed.mjs http://localhost:5173 ./out.json [selectors.txt]
//
// 依赖：playwright（项目里通常已有；没有就 `pnpm add -D playwright && npx playwright install chromium`）

import { chromium } from 'playwright';
import fs from 'node:fs';

const url = process.argv[2] || 'http://localhost:5173';
const out = process.argv[3] || 'computed.json';
const selFile = process.argv[4];

const PROPS = [
  'borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius',
  'borderRadius',
  'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
  'marginTop', 'marginRight', 'marginBottom', 'marginLeft',
  'fontSize', 'lineHeight', 'letterSpacing', 'fontWeight', 'fontFamily',
  'boxSizing', 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
  'zoom', 'transform',
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(url, { waitUntil: 'networkidle' });
// 等字体加载，否则字号/行高会按 fallback 度量算出来
await page.evaluate(() => document.fonts.ready.then(() => true));

let targets;
if (selFile && fs.existsSync(selFile)) {
  const sels = fs.readFileSync(selFile, 'utf8').split('\n').map((s) => s.trim()).filter(Boolean);
  targets = sels.map((s) => ({ selector: s, key: s }));
} else {
  targets = await page.$$eval('[data-ds]', (els) =>
    els.map((el, i) => ({
      selector: `[data-ds="${el.getAttribute('data-ds')}"]`,
      key: el.getAttribute('data-ds') || `el${i}`,
    })),
  );
}

const dpr = await page.evaluate(() => window.devicePixelRatio);
const nodes = [];
for (const t of targets) {
  const data = await page.$$eval(t.selector, (els, props) => {
    return els.map((el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const style = {};
      for (const p of props) style[p] = cs[p];
      return { rect: { x: r.x, y: r.y, w: r.width, h: r.height }, style };
    });
  }, PROPS);
  for (const d of data) nodes.push({ key: t.key, selector: t.selector, ...d });
}

fs.writeFileSync(out, JSON.stringify({ url, viewport: { w: 1440, h: 900, dpr }, nodes }, null, 2));
console.log(`captured ${nodes.length} nodes -> ${out} (dpr=${dpr})`);
await browser.close();
