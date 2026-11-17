#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sketch_reader.py — 把 MasterGo 导出的 .sketch 解成"可对齐的设计规格 JSON"。

.sketch 本质是 zip：
    document.json      共享样式 + pages 索引
    meta.json          页面/画板清单、字体清单
    user.json          UI 状态
    pages/<uuid>.json  图层树（真正的内容）
    images/            位图资源

零依赖，只用标准库。设计工具里没有 margin，只有绝对几何；
因此本脚本除了直接读属性，还会推导 visualPadding / visualGap，
这才是实现端 padding 与 margin 的来源。

用法：
    python3 sketch_reader.py a.sketch -o a.spec.json
    python3 sketch_reader.py a.sketch --ai        # 输出 AI 友好的紧凑文本
"""
import argparse
import json
import os
import sys
import zipfile

TEXT_CLASSES = {"text", "MSImmutableText", "attributedText"}
CONTAINER_CLASSES = {"artboard", "page", "group", "symbolMaster", "shapeGroup", "MSImmutableGroup"}


# ---------------------------------------------------------------- helpers
def _n(v, d=None):
    if isinstance(v, bool):
        return d
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    return d


def _hex(color):
    if not isinstance(color, dict):
        return None
    r = color.get("red", 0) or 0
    g = color.get("green", 0) or 0
    b = color.get("blue", 0) or 0
    a = color.get("alpha", 1)
    if a is None:
        a = 1
    h = "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))
    return h if a >= 0.999 else "%s/%.0f%%" % (h, a * 100)


def _frame(lay):
    f = lay.get("frame") or {}
    return {
        "x": _n(f.get("x"), 0),
        "y": _n(f.get("y"), 0),
        "w": _n(f.get("width"), 0),
        "h": _n(f.get("height"), 0),
    }


def _corners(lay):
    """sketch: fixedRadius 单值；或 points[].cornerRadius 四角（顺时针 TL/TR/BR/BL）。"""
    fixed = _n(lay.get("fixedRadius"))
    pts = lay.get("points") or []
    per = []
    for p in pts:
        if isinstance(p, dict):
            per.append(_n(p.get("cornerRadius"), 0))
    if len(per) == 4 and any(x for x in per):
        return {"all": None, "tl": per[0], "tr": per[1], "br": per[2], "bl": per[3]}
    if fixed is not None:
        return {"all": fixed, "tl": fixed, "tr": fixed, "br": fixed, "bl": fixed}
    return None


def _layout(lay):
    """自动布局 -> CSS flex 等价物。axis: 0=横向(row) 1=纵向(column)。"""
    gl = lay.get("groupLayout")
    if not isinstance(gl, dict):
        return None
    axis = gl.get("axis")
    return {
        "axis": "row" if axis in (0, "0", None) else "column",
        "padding": {
            "top": _n(gl.get("paddingTop"), 0),
            "right": _n(gl.get("paddingRight"), 0),
            "bottom": _n(gl.get("paddingBottom"), 0),
            "left": _n(gl.get("paddingLeft"), 0),
        },
        "gap": _n(gl.get("itemSpacing"), 0),
        "alignItems": gl.get("alignItems"),
        "justifyContent": gl.get("justifyContent"),
        "distribute": gl.get("distribute"),
        "sizing": {"w": gl.get("widthSizing"), "h": gl.get("heightSizing")},
    }


ALIGN = {0: "left", 1: "right", 2: "center", 3: "justify"}


def _text(lay):
    ats = lay.get("attributedString")
    if not isinstance(ats, dict):
        return None
    runs = ats.get("attributes") or []
    first = (runs[0].get("attributes") if runs and isinstance(runs[0], dict) else {}) or {}
    font = first.get("MSAttributedStringFontAttribute") or {}
    fa = font.get("attributes") or {}
    para = first.get("paragraphStyle") or {}
    lh = para.get("maximumLineHeight")
    if lh is None:
        lh = para.get("minimumLineHeight")
    return {
        "string": (ats.get("string") or "")[:200],
        "fontFamily": fa.get("name"),
        "fontSize": _n(fa.get("size")),
        "lineHeight": _n(lh),
        "lineHeightAuto": lh is None,
        "letterSpacing": _n(first.get("kerning"), 0),
        "textAlign": ALIGN.get(para.get("alignment")),
        "runCount": len(runs),
    }


def _style(lay):
    st = lay.get("style") or {}
    fills = []
    for f in (st.get("fills") or []):
        if isinstance(f, dict) and f.get("isEnabled", True):
            fills.append({"color": _hex(f.get("color")), "type": f.get("fillType")})
    borders = []
    for b in (st.get("borders") or []):
        if isinstance(b, dict) and b.get("isEnabled", True):
            borders.append(
                {
                    "color": _hex(b.get("color")),
                    "thickness": _n(b.get("thickness")),
                    "position": (b.get("position")),
                }
            )
    bo = st.get("borderOptions") or {}
    if not fills and not borders:
        return None
    return {"fills": fills, "borders": borders, "borderPosition": bo.get("lineCapStyle")}


# ---------------------------------------------------------------- walk
def _extract(lay, uid, parent_uid, depth):
    cls = lay.get("_class") or "unknown"
    st_raw = lay.get("style")
    st_raw = st_raw if isinstance(st_raw, dict) else {}
    cs = st_raw.get("contextSettings") if isinstance(st_raw.get("contextSettings"), dict) else {}
    node = {
        "uid": uid,
        "parent": parent_uid,
        "depth": depth,
        "name": lay.get("name"),
        "type": cls,
        "frame": _frame(lay),
        "visible": lay.get("isVisible", True),
        "opacity": _n(cs.get("opacity"), _n(lay.get("opacity"), 1)),
    }
    cr = _corners(lay)
    if cr:
        node["cornerRadius"] = cr
    lay_ = _layout(lay)
    if lay_:
        node["layout"] = lay_
    tx = _text(lay)
    if tx:
        node["text"] = tx
    st = _style(lay)
    if st:
        node["style"] = st
    return node


def walk_page(page):
    nodes = []
    counter = [0]

    def rec(layers, parent_uid, depth, path):
        for lay in layers or []:
            if not isinstance(lay, dict):
                continue
            counter[0] += 1
            uid = "n%d" % counter[0]
            node = _extract(lay, uid, parent_uid, depth)
            node["path"] = "/".join(path + [str(node.get("name"))])
            nodes.append(node)
            rec(lay.get("layers"), uid, depth + 1, path + [str(node.get("name"))])

    rec(page.get("layers"), None, 0, [])
    return nodes


# ---------------------------------------------------------------- derive
def derive_geometry(nodes):
    """
    设计工具只有绝对坐标，没有 margin。这里补两类"视觉量"：
      visualPadding —— 子节点包围盒到父容器的四边距离（实现端 padding 的真相）
      visualGap     —— 同一父级下、按主轴的相邻兄弟间距（实现端 gap/margin 的真相）
    只在父容器是容器类且尺寸有效时计算。
    """
    by_uid = {n["uid"]: n for n in nodes}
    children = {}
    for n in nodes:
        children.setdefault(n["parent"], []).append(n)

    for n in nodes:
        p = by_uid.get(n["parent"])
        if not p:
            continue
        # sketch 的 frame 本来就是相对父级的坐标，不要再减父的 x/y
        pf, nf = p["frame"], n["frame"]
        if not pf["w"] or not pf["h"]:
            continue
        # 父级已是自动布局时，间距由父的 padding/gap 表达，这里不重复推导
        if p.get("layout"):
            continue
        n["visualPadding"] = {
            "left": _n(nf["x"]),
            "top": _n(nf["y"]),
            "right": _n(pf["w"] - (nf["x"] + nf["w"])),
            "bottom": _n(pf["h"] - (nf["y"] + nf["h"])),
        }

    for pid, kids in children.items():
        if pid is None or len(kids) < 2:
            continue
        lay = by_uid[pid].get("layout") if pid in by_uid else None
        axis = (lay or {}).get("axis")
        if axis == "row":
            kids_sorted = sorted(kids, key=lambda k: k["frame"]["x"])
            for a, b in zip(kids_sorted, kids_sorted[1:]):
                gap = _n(b["frame"]["x"] - (a["frame"]["x"] + a["frame"]["w"]))
                if gap is not None and gap >= 0:
                    b["visualGap"] = gap
        elif axis == "column":
            kids_sorted = sorted(kids, key=lambda k: k["frame"]["y"])
            for a, b in zip(kids_sorted, kids_sorted[1:]):
                gap = _n(b["frame"]["y"] - (a["frame"]["y"] + a["frame"]["h"]))
                if gap is not None and gap >= 0:
                    b["visualGap"] = gap
    return nodes


# ---------------------------------------------------------------- public
def read_sketch(path):
    if not zipfile.is_zipfile(path):
        raise SystemExit("%s 不是 zip/sketch 文件" % path)
    zf = zipfile.ZipFile(path)
    names = zf.namelist()
    page_files = sorted([n for n in names if n.startswith("pages/") and n.endswith(".json")])
    meta = {}
    if "meta.json" in names:
        try:
            meta = json.loads(zf.read("meta.json").decode("utf-8"))
        except Exception:
            meta = {}
    pages = []
    for pf in page_files:
        try:
            pg = json.loads(zf.read(pf).decode("utf-8"))
        except Exception:
            continue
        nodes = derive_geometry(walk_page(pg))
        pages.append(
            {
                "page": pg.get("name"),
                "file": pf,
                "nodes": nodes,
            }
        )
    return {
        "source": os.path.basename(path),
        "kind": "sketch",
        "meta": {
            "appVersion": meta.get("appVersion"),
            "fonts": meta.get("fonts"),
            "pagesAndArtboards": list((meta.get("pagesAndArtboards") or {}).keys()),
        },
        "pages": pages,
    }


def to_ai_text(spec, only=None):
    """紧凑文本，给 LLM 直接读，token 友好。"""
    keep = only or {"cornerRadius", "layout", "text", "visualPadding", "visualGap"}
    out = []
    for pg in spec["pages"]:
        out.append("## page: %s" % pg["page"])
        for n in pg["nodes"]:
            if n["type"] in ("slice",):
                continue
            bits = ["[%s] %s" % (n["type"], n["name"])]
            f = n["frame"]
            bits.append("box %gx%g @(%g,%g)" % (f["w"], f["h"], f["x"], f["y"]))
            if "cornerRadius" in n:
                c = n["cornerRadius"]
                bits.append("radius %s" % (c["all"] if c["all"] is not None
                                           else "%g/%g/%g/%g" % (c["tl"], c["tr"], c["br"], c["bl"])))
            if "layout" in n:
                L = n["layout"]
                p = L["padding"]
                bits.append("autolayout %s pad(t%g r%g b%g l%g) gap %g"
                            % (L["axis"], p["top"], p["right"], p["bottom"], p["left"], L["gap"]))
            if "visualPadding" in n and "layout" not in n:
                v = n["visualPadding"]
                bits.append("visualPad(t%g r%g b%g l%g)" % (v["top"], v["right"], v["bottom"], v["left"]))
            if "visualGap" in n:
                bits.append("visualGap %g" % n["visualGap"])
            if "text" in n:
                t = n["text"]
                bits.append("text %r %s %gpx lh=%s ls=%s align=%s"
                            % (t["string"][:40], t["fontFamily"], t["fontSize"] or 0,
                               ("auto" if t["lineHeightAuto"] else t["lineHeight"]),
                               t["letterSpacing"], t["textAlign"]))
            out.append("  " + " | ".join(bits))
    return "\n".join(out)


def lint(spec):
    """
    导出体检：检查 .sketch 导出过程中容易发生的"变形"。
    重点不是判断对错，而是把风险量化出来，让你知道哪些数值不能直接信。
    """
    issues = []
    fonts = {}
    stat = {"nodes": 0, "withRadius": 0, "withAutoLayout": 0, "withText": 0,
            "withVisualPadding": 0, "hidden": 0}
    for pg in spec["pages"]:
        nodes = pg["nodes"]
        by_uid = {n["uid"]: n for n in nodes}
        for n in nodes:
            stat["nodes"] += 1
            f = n["frame"]
            w, h = f["w"] or 0, f["h"] or 0
            name = n.get("name")

            if not n.get("visible", True):
                stat["hidden"] += 1

            c = n.get("cornerRadius")
            if c:
                stat["withRadius"] += 1
                vals = [v for v in (c.get("tl"), c.get("tr"), c.get("br"), c.get("bl"))
                        if isinstance(v, (int, float))]
                if vals and min(w, h) > 0:
                    mx = max(vals)
                    if mx > min(w, h) / 2 + 0.5:
                        issues.append(
                            "[胶囊/裁切] %s radius=%g 超过短边一半(%.1f)，浏览器会按胶囊裁切"
                            % (name, mx, min(w, h) / 2))
                if len(set(vals)) > 1:
                    issues.append("[四角不等] %s radius=%s，实现端不要写简写"
                                  % (name, "/".join("%g" % v for v in vals)))

            L = n.get("layout")
            if L:
                stat["withAutoLayout"] += 1
                p = L["padding"]
                for k, v in p.items():
                    if isinstance(v, (int, float)) and v < 0:
                        issues.append("[负 padding] %s padding%s=%g" % (name, k, v))
                if isinstance(L.get("gap"), (int, float)) and L["gap"] < 0:
                    issues.append("[负 gap] %s gap=%g" % (name, L["gap"]))
                horiz = (p["left"] or 0) + (p["right"] or 0)
                vert = (p["top"] or 0) + (p["bottom"] or 0)
                if w and horiz >= w:
                    issues.append("[溢出] %s 左右 padding 合计 %g >= 宽度 %g，子元素会被挤爆"
                                  % (name, horiz, w))
                if h and vert >= h:
                    issues.append("[溢出] %s 上下 padding 合计 %g >= 高度 %g" % (name, vert, h))
                kids = [k for k in nodes if k["parent"] == n["uid"]]
                if len(kids) >= 2 and not L.get("gap"):
                    issues.append("[间距缺失] %s 有 %d 个子节点但 gap=0，可能是导出丢了间距"
                                  % (name, len(kids)))

            if "visualPadding" in n:
                stat["withVisualPadding"] += 1

            t = n.get("text")
            if t:
                stat["withText"] += 1
                fam = t.get("fontFamily")
                if fam:
                    fonts[fam] = fonts.get(fam, 0) + 1
                fs = t.get("fontSize")
                if not fs or fs <= 0:
                    issues.append("[字号缺失] %s fontSize=%s，导出或字体样式绑定丢了" % (name, fs))
                elif h and h > fs * 3.5:
                    issues.append("[行盒异常] %s 高度 %.1f 是字号的 %.1f 倍，检查 line-height"
                                  % (name, h, h / fs))
                if w and w < fs and (t.get("string") or ""):
                    issues.append("[宽度塌陷] %s 宽度 %.1f < 字号 %s，字体可能 fallback 了"
                                  % (name, w, fs))

    # 字体可用性（本机装了没有，影响你换机器后复核）
    missing = []
    try:
        import subprocess
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True,
                             text=True, timeout=10).stdout
        have = out.lower()
        for fam in fonts:
            base = fam.split("-")[0].replace(" ", "").lower()
            if base and base not in have.replace(" ", ""):
                missing.append(fam)
    except Exception:
        missing = []

    return {"stat": stat, "fonts": fonts, "missingFonts": missing, "issues": issues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sketch")
    ap.add_argument("-o", "--out")
    ap.add_argument("--ai", action="store_true", help="输出 AI 友好紧凑文本")
    ap.add_argument("--lint", action="store_true", help="导出体检：找出可能变形的数值")
    ap.add_argument("--page")
    a = ap.parse_args()
    spec = read_sketch(a.sketch)
    if a.page:
        spec["pages"] = [p for p in spec["pages"] if p["page"] == a.page]
    if a.lint:
        r = lint(spec)
        lines = ["== stat =="]
        for k, v in r["stat"].items():
            lines.append("  %-18s %s" % (k, v))
        lines.append("== fonts ==")
        for f, c in sorted(r["fonts"].items(), key=lambda x: -x[1]):
            lines.append("  %-32s x%d%s" % (f, c, "  [本机缺失]" if f in r["missingFonts"] else ""))
        lines.append("== issues (%d) ==" % len(r["issues"]))
        for i in r["issues"][:60]:
            lines.append("  - " + i)
        txt = "\n".join(lines)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(txt)
        else:
            sys.stdout.write(txt + "\n")
        return
    if a.ai:
        txt = to_ai_text(spec)
        if a.out:
            open(a.out, "w", encoding="utf-8").write(txt)
        else:
            sys.stdout.write(txt)
        return
    txt = json.dumps(spec, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(txt)
        n = sum(len(p["nodes"]) for p in spec["pages"])
        sys.stderr.write("ok: %d pages, %d nodes -> %s\n" % (len(spec["pages"]), n, a.out))
    else:
        sys.stdout.write(txt)


if __name__ == "__main__":
    main()
