/**
 * Design Spec Export — MasterGo 插件主进程（沙箱内）
 *
 * 目标：把当前设计稿的 border-radius / padding / gap / font-size 直接读出来，
 * 输出成与 sketch_reader.py 完全一致的结构，让 compare.py / server.py 零改动吃得下。
 *
 * 数据从 MasterGo 内存直读，不经过任何格式转换 —— 不存在"导 sketch 会变形"的问题。
 */

const api = typeof mg !== 'undefined' ? mg : figma;

// ---------------------------------------------------------------- utils
function num(v, d) {
  return typeof v === 'number' && isFinite(v) ? Math.round(v * 100) / 100 : d;
}

function isMixed(v) {
  return typeof v === 'symbol';
}

function rgbToHex(c, opacity) {
  if (!c || typeof c !== 'object') return null;
  const to = (x) => Math.max(0, Math.min(255, Math.round((x || 0) * 255)));
  const h = '#' + [to(c.r), to(c.g), to(c.b)].map((x) => x.toString(16).padStart(2, '0')).join('').toUpperCase();
  const a = typeof opacity === 'number' ? opacity : (typeof c.a === 'number' ? c.a : 1);
  return a >= 0.999 ? h : h + '/' + Math.round(a * 100) + '%';
}

function corners(n) {
  if (typeof n.cornerRadius === 'number') {
    const r = n.cornerRadius;
    return { all: r, tl: r, tr: r, br: r, bl: r };
  }
  const tl = n.topLeftRadius;
  const tr = n.topRightRadius;
  const br = n.bottomRightRadius;
  const bl = n.bottomLeftRadius;
  if ([tl, tr, br, bl].some((v) => typeof v === 'number')) {
    return { all: null,
      tl: num(tl, 0), tr: num(tr, 0), br: num(br, 0), bl: num(bl, 0) };
  }
  return null;
}

const ALIGN_MAP = {
  MIN: 'flex-start', MAX: 'flex-end', CENTER: 'center',
  SPACE_BETWEEN: 'space-between', SPACE_AROUND: 'space-around',
  SPACE_EVENLY: 'space-evenly', BASELINE: 'baseline',
};

function layoutOf(n) {
  const mode = n.layoutMode;
  if (mode !== 'HORIZONTAL' && mode !== 'VERTICAL') return null;
  return {
    axis: mode === 'HORIZONTAL' ? 'row' : 'column',
    padding: {
      top: num(n.paddingTop, 0),
      right: num(n.paddingRight, 0),
      bottom: num(n.paddingBottom, 0),
      left: num(n.paddingLeft, 0),
    },
    gap: num(n.itemSpacing, 0),
    counterGap: num(n.counterAxisSpacing, null),
    alignItems: ALIGN_MAP[n.counterAxisAlignItems] || n.counterAxisAlignItems || null,
    justifyContent: ALIGN_MAP[n.primaryAxisAlignItems] || n.primaryAxisAlignItems || null,
    wrap: n.layoutWrap || null,
    sizing: {
      w: n.layoutSizingHorizontal || n.primaryAxisSizingMode || null,
      h: n.layoutSizingVertical || n.counterAxisSizingMode || null,
    },
  };
}

function lineHeightOf(n) {
  const lh = n.lineHeight;
  if (!lh || typeof lh !== 'object') return { value: null, auto: true };
  if (lh.unit === 'PIXELS') return { value: num(lh.value, null), auto: false };
  if (lh.unit === 'PERCENT' && typeof n.fontSize === 'number') {
    return { value: num((n.fontSize * lh.value) / 100, null), auto: false };
  }
  return { value: null, auto: true };
}

function letterSpacingOf(n) {
  const ls = n.letterSpacing;
  if (!ls || typeof ls !== 'object') return 0;
  if (ls.unit === 'PIXELS') return num(ls.value, 0);
  if (ls.unit === 'PERCENT' && typeof n.fontSize === 'number') {
    return num((n.fontSize * ls.value) / 100, 0);
  }
  return 0;
}

function fillsOf(n) {
  const out = [];
  const arr = n.fills;
  if (Array.isArray(arr)) {
    for (const f of arr) {
      if (!f || f.visible === false) continue;
      out.push({ color: f.type === 'SOLID' ? rgbToHex(f.color, f.opacity) : null, type: f.type });
    }
  }
  return out;
}

function strokesOf(n) {
  const out = [];
  if (Array.isArray(n.strokes) && n.strokes.length) {
    const w = num(n.strokeWeight, null);
    const align = n.strokeAlign || null;
    for (const s of n.strokes) {
      if (!s || s.visible === false) continue;
      out.push({ color: s.type === 'SOLID' ? rgbToHex(s.color, s.opacity) : null,
        thickness: w, position: align });
    }
  }
  return out;
}

// ---------------------------------------------------------------- fonts
const loadedFonts = new Set();

async function ensureFont(n) {
  if (n.type !== 'TEXT') return;
  const fn = n.fontName;
  if (!fn || isMixed(fn) || typeof fn !== 'object') return;
  const key = (fn.family || '') + '|' + (fn.style || '');
  if (loadedFonts.has(key)) return;
  try {
    if (typeof api.loadFontAsync === 'function') {
      await api.loadFontAsync({ family: fn.family, style: fn.style });
    }
    loadedFonts.add(key);
  } catch (e) {
    // 字体缺失也不能中断导出，记下来在 UI 里提示
    loadedFonts.add(key);
  }
}

// ---------------------------------------------------------------- collect
function makeNodeRec(n, parentUid, depth, path) {
  const rec = {
    uid: n.id || ('auto' + Math.random().toString(36).slice(2, 9)),
    parent: parentUid,
    depth: depth,
    name: n.name,
    type: n.type,
    path: (path.length ? path.join('/') + '/' : '') + String(n.name),
    frame: {
      x: num(n.x, 0),
      y: num(n.y, 0),
      w: num(n.width, 0),
      h: num(n.height, 0),
    },
    visible: n.visible !== false,
    opacity: num(n.opacity, 1),
  };

  const cr = corners(n);
  if (cr) rec.cornerRadius = cr;

  const lay = layoutOf(n);
  if (lay) rec.layout = lay;

  if (n.type === 'TEXT') {
    const lh = lineHeightOf(n);
    const fn = n.fontName;
    rec.text = {
      string: typeof n.characters === 'string' ? n.characters.slice(0, 200) : '',
      fontFamily: fn && !isMixed(fn) ? (fn.family + (fn.style && fn.style !== 'Regular' ? '-' + fn.style : '')) : null,
      fontSize: num(n.fontSize, null),
      lineHeight: lh.value,
      lineHeightAuto: lh.auto,
      letterSpacing: letterSpacingOf(n),
      textAlign: n.textAlignHorizontal ? String(n.textAlignHorizontal).toLowerCase() : null,
      fontWeight: fn && !isMixed(fn) ? fn.style : null,
      autoResize: n.textAutoResize || null,
    };
  }

  const fills = fillsOf(n);
  const strokes = strokesOf(n);
  if (fills.length || strokes.length) rec.style = { fills, borders: strokes };

  if (n.absoluteBoundingBox) {
    rec.absoluteBoundingBox = {
      x: num(n.absoluteBoundingBox.x, 0),
      y: num(n.absoluteBoundingBox.y, 0),
      w: num(n.absoluteBoundingBox.width, 0),
      h: num(n.absoluteBoundingBox.height, 0),
    };
  }
  return rec;
}

function deriveGeometry(nodes) {
  const byUid = {};
  const children = {};
  for (const n of nodes) {
    byUid[n.uid] = n;
    (children[n.parent] = children[n.parent] || []).push(n);
  }

  for (const n of nodes) {
    const p = byUid[n.parent];
    if (!p || p.layout) continue;           // 父级是自动布局时，间距由 padding/gap 表达
    const pf = p.frame, nf = n.frame;
    if (!pf.w || !pf.h) continue;
    n.visualPadding = {
      left: num(nf.x, 0),
      top: num(nf.y, 0),
      right: num(pf.w - (nf.x + nf.w), 0),
      bottom: num(pf.h - (nf.y + nf.h), 0),
    };
  }

  for (const pid in children) {
    const kids = children[pid];
    if (!pid || pid === 'null' || kids.length < 2) continue;
    const p = byUid[pid];
    const axis = p && p.layout ? p.layout.axis : null;
    if (axis === 'row') {
      kids.slice().sort((a, b) => a.frame.x - b.frame.x).reduce((a, b) => {
        const gap = num(b.frame.x - (a.frame.x + a.frame.w), null);
        if (gap !== null && gap >= 0) b.visualGap = gap;
        return b;
      });
    } else if (axis === 'column') {
      kids.slice().sort((a, b) => a.frame.y - b.frame.y).reduce((a, b) => {
        const gap = num(b.frame.y - (a.frame.y + a.frame.h), null);
        if (gap !== null && gap >= 0) b.visualGap = gap;
        return b;
      });
    }
  }
  return nodes;
}

async function collectTree(roots, includeHidden, onProgress) {
  const nodes = [];
  let visited = 0;

  async function walk(children, parentUid, depth, path) {
    for (const n of children || []) {
      if (!includeHidden && n.visible === false) continue;
      visited++;
      if (visited % 120 === 0) onProgress(visited);
      await ensureFont(n);
      const rec = makeNodeRec(n, parentUid, depth, path);
      nodes.push(rec);
      if ('children' in n && Array.isArray(n.children) && n.children.length) {
        await walk(n.children, rec.uid, depth + 1, path.concat([String(n.name)]));
      }
    }
  }

  await walk(roots, null, 0, []);
  return deriveGeometry(nodes);
}

// ---------------------------------------------------------------- ai text
function toAiText(spec, limit) {
  const out = [];
  for (const pg of spec.pages) {
    out.push('## page: ' + pg.page);
    for (const n of pg.nodes) {
      if (n.type === 'SLICE') continue;
      const bits = ['[' + n.type + '] ' + n.name];
      const f = n.frame;
      bits.push('box ' + f.w + 'x' + f.h + ' @(' + f.x + ',' + f.y + ')');
      if (n.cornerRadius) {
        const c = n.cornerRadius;
        bits.push('radius ' + (c.all !== null ? c.all : [c.tl, c.tr, c.br, c.bl].join('/')));
      }
      if (n.layout) {
        const p = n.layout.padding;
        bits.push('autolayout ' + n.layout.axis + ' pad(t' + p.top + ' r' + p.right +
          ' b' + p.bottom + ' l' + p.left + ') gap ' + n.layout.gap);
      }
      if (n.visualPadding && !n.layout) {
        const v = n.visualPadding;
        bits.push('visualPad(t' + v.top + ' r' + v.right + ' b' + v.bottom + ' l' + v.left + ')');
      }
      if (typeof n.visualGap === 'number') bits.push('visualGap ' + n.visualGap);
      if (n.text) {
        const t = n.text;
        bits.push('text "' + t.string.slice(0, 40) + '" ' + t.fontFamily + ' ' + t.fontSize +
          'px lh=' + (t.lineHeightAuto ? 'auto' : t.lineHeight) + ' ls=' + t.letterSpacing);
      }
      out.push('  ' + bits.join(' | '));
      if (limit && out.length > limit) {
        out.push('  ...(截断)');
        return out.join('\n');
      }
    }
  }
  return out.join('\n');
}

// ---------------------------------------------------------------- main
api.showUI(__html__, { width: 560, height: 600, title: 'Design Spec Export' });

function stat(spec) {
  const s = { nodes: 0, withRadius: 0, withAutoLayout: 0, withText: 0, hidden: 0 };
  for (const pg of spec.pages) {
    for (const n of pg.nodes) {
      s.nodes++;
      if (n.cornerRadius) s.withRadius++;
      if (n.layout) s.withAutoLayout++;
      if (n.text) s.withText++;
      if (n.visible === false) s.hidden++;
    }
  }
  return s;
}

async function run(scope, includeHidden) {
  const t0 = Date.now();
  let roots;
  let pageName = 'page';
  if (scope === 'selection') {
    roots = api.currentPage.selection;
    pageName = 'selection';
    if (!roots || !roots.length) {
      api.ui.postMessage({ type: 'error', message: '没有选中任何图层' });
      return;
    }
  } else {
    roots = api.currentPage.children;
    pageName = api.currentPage.name || 'page';
  }

  api.ui.postMessage({ type: 'progress', message: '开始遍历…' });
  const nodes = await collectTree(roots, includeHidden, (v) => {
    api.ui.postMessage({ type: 'progress', message: '已遍历 ' + v + ' 个图层…' });
  });

  const spec = {
    source: 'mastergo-plugin',
    kind: 'plugin',
    generatedAt: new Date().toISOString(),
    meta: { file: api.root && api.root.name, page: pageName, scope: scope },
    pages: [{ page: pageName, nodes: nodes }],
  };

  api.ui.postMessage({
    type: 'result',
    spec: spec,
    stat: stat(spec),
    ai: toAiText(spec, 4000),
    ms: Date.now() - t0,
  });
}

api.ui.onmessage = async (msg) => {
  // MasterGo 传的是 raw object；兼容 Figma 的 { pluginMessage } 包装
  const m = msg && (msg.pluginMessage || msg);
  if (!m || !m.type) return;
  if (m.type === 'run') {
    await run(m.scope || 'page', !!m.includeHidden);
  }
};

// 通过菜单命令直接进入对应模式（若平台支持 mg.command）
try {
  const cmd = api.command;
  if (typeof cmd === 'string') {
    setTimeout(() => run(cmd === 'selection' ? 'selection' : 'page', cmd === 'page-all'), 200);
  }
} catch (e) {}
