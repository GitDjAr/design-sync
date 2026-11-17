#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare.py — 设计规格 vs 浏览器实际计算样式，逐属性对账。

设计侧  : sketch_reader.py / mg_reader.py 产出的 *.spec.json
实现侧  : capture-computed.mjs 产出的 *.computed.json

匹配规则（按优先级）：
  1. computed 节点带 "key"，等于设计节点的 path 末尾或 name
  2. computed 节点带 "key"，用包含/模糊匹配
  3. computed 节点带 "selector"，设计节点名做 slug 比较（去掉 / . : 空格）

只对账 4 类问题属性（可扩展）：border-radius / padding / margin / font-size
并按根因规则给出候选解释——这些才是反复返工的真正原因。

用法：
    python3 compare.py design.spec.json page.computed.json
    python3 compare.py design.spec.json page.computed.json --tol 0.5 --json
"""
import argparse
import json
import re
import sys

PROPS = ["borderRadius", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
         "marginTop", "marginRight", "marginBottom", "marginLeft",
         "fontSize", "lineHeight", "letterSpacing"]


def px(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    m = re.match(r"^(-?\d*\.?\d+)\s*(px|rem|em)?$", s)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2)
    if unit == "rem":
        num *= 16
    elif unit == "em":
        num *= 16
    return round(num, 4)


def radius_all(style):
    """CSS border-radius 可能是 8px / 8px 4px / 50%。取四角。"""
    raw = style.get("borderRadius")
    if not raw:
        return None
    parts = [p for p in str(raw).replace("/", " ").split() if p]
    vals = [px(p) for p in parts]
    if any(v is None for v in vals):
        return None
    if len(vals) == 1:
        return vals * 4
    if len(vals) == 2:
        return [vals[0], vals[1], vals[0], vals[1]]
    if len(vals) == 3:
        return [vals[0], vals[1], vals[2], vals[1]]
    return vals[:4]


def design_radius(node):
    c = node.get("cornerRadius")
    if not c:
        return None
    if c.get("all") is not None:
        return [c["all"]] * 4
    return [c.get("tl"), c.get("tr"), c.get("br"), c.get("bl")]


def design_padding(node):
    L = node.get("layout")
    if L:
        p = L["padding"]
        return [p["left"], p["top"], p["right"], p["bottom"]]
    v = node.get("visualPadding")
    if v:
        return [v["left"], v["top"], v["right"], v["bottom"]]
    return None


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def build_index(spec):
    idx = {}
    for pg in spec.get("pages", []):
        for n in pg.get("nodes", []):
            keys = set()
            if n.get("name"):
                keys.add(norm(n["name"]))
            if n.get("path"):
                keys.add(norm(n["path"]))
                keys.add(norm(str(n["path"]).split("/")[-1]))
            for k in keys:
                if k:
                    idx.setdefault(k, n)
    return idx


def match(comp_node, idx):
    key = norm(comp_node.get("key"))
    if key:
        if key in idx:
            return idx[key]
        if ":" in key:  # "Button/Primary:primary" 这类
            head = norm(key.split(":")[0])
            if head in idx:
                return idx[head]
        for k, v in idx.items():
            if key and (key in k or k in key) and len(k) > 2:
                return v
    return None


def diff_node(design, comp, tol):
    ds, cs = comp.get("style") or {}, comp.get("style") or {}
    rows = []

    dr, cr = design_radius(design), radius_all(cs)
    if dr and cr:
        names = ["tl", "tr", "br", "bl"]
        for i, nm in enumerate(names):
            d, c = dr[i], cr[i]
            if d is None or c is None:
                continue
            if abs(d - c) > tol:
                rows.append(("border-radius." + nm, d, c, "radius"))

    dp = design_padding(design)
    # 文本节点没有 padding 概念，只有外层容器才有
    if dp and str(design.get("type")) != "text":
        for i, nm in enumerate(["Left", "Top", "Right", "Bottom"]):
            c = px(cs.get("padding" + nm))
            if c is None or dp[i] is None:
                continue
            if abs(dp[i] - c) > tol:
                rows.append(("padding" + nm, dp[i], c, "padding"))

    # margin：设计侧只有视觉间距，没有 margin 概念
    vg = design.get("visualGap")
    mt, mb = px(cs.get("marginTop")), px(cs.get("marginBottom"))
    for side, c in (("Top", mt), ("Bottom", mb)):
        if c is None:
            continue
        if vg is not None and abs(vg - (-c)) > tol and abs(vg - c) > tol and c != 0:
            rows.append(("margin" + side, vg, c, "margin"))

    dt = design.get("text") or {}
    for prop, dkey in (("fontSize", "fontSize"), ("lineHeight", "lineHeight"),
                       ("letterSpacing", "letterSpacing")):
        d = dt.get(dkey)
        c = px(cs.get(prop))
        if d is None or c is None:
            continue
        if prop == "lineHeight" and dt.get("lineHeightAuto"):
            continue
        if abs(d - c) > tol:
            rows.append((prop, d, c, "type"))

    return rows


def explain(prop, comp):
    """把差异翻译成最可能的根因，这是返工省时间的地方。"""
    st = comp.get("style") or {}
    dpr = comp.get("viewport", {}).get("dpr", 1)
    bw = max([px(st.get("border" + s + "Width")) or 0
              for s in ("Top", "Right", "Bottom", "Left")] or [0])
    bs = st.get("boxSizing")
    if prop.startswith("border-radius"):
        if bw and bs == "content-box":
            return "border 占位后外径变大：改用 box-sizing:border-box，或把 radius 加到 border 外径"
        if dpr and dpr > 1:
            return "DPR=%s 下 1px 取整偏差：设计稿若是 2x 导出需整体 /2" % dpr
        return "检查 overflow:hidden 裁切、border 与 background 分层、父级 transform 缩放"
    if prop.startswith("padding"):
        if bs == "content-box":
            return "box-sizing:content-box 会把 padding 加在宽度外，设计稿通常是 border-box 语义"
        return "核对自动布局 padding 是否被 gap/margin 重复叠加；MasterGo 缺失值默认 10px"
    if prop.startswith("margin"):
        return "设计工具没有 margin 概念：用自动布局的 gap 实现，不要用 margin+last-child 补"
    if prop in ("fontSize", "lineHeight", "letterSpacing"):
        if st.get("zoom") not in (None, "1", "normal"):
            return "存在 zoom/scale，计算值被缩放"
        return "字体 fallback 导致度量不同；确认设计字体在实现端已加载，line-height 用 px 而非固定倍数"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("computed")
    ap.add_argument("--tol", type=float, default=0.5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    spec = json.load(open(a.design, encoding="utf-8"))
    comp = json.load(open(a.computed, encoding="utf-8"))
    idx = build_index(spec)

    report = {"checked": 0, "matched": 0, "unmatched": [], "diffs": []}
    for c in comp.get("nodes", []):
        report["checked"] += 1
        d = match(c, idx)
        if d is None:
            report["unmatched"].append(c.get("key") or c.get("selector"))
            continue
        report["matched"] += 1
        for prop, dv, cv, kind in diff_node(d, c, a.tol):
            report["diffs"].append({
                "layer": d.get("name"), "key": c.get("key") or c.get("selector"),
                "prop": prop, "design": dv, "actual": cv,
                "delta": round((cv or 0) - (dv or 0), 3),
                "hint": explain(prop, c),
            })

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print("检查节点 %d，匹配 %d，未匹配 %d，差异 %d"
          % (report["checked"], report["matched"], len(report["unmatched"]), len(report["diffs"])))
    if report["unmatched"]:
        print("\n未匹配（检查 data-ds-name / key 命名）:")
        for u in report["unmatched"][:30]:
            print("  -", u)
    if report["diffs"]:
        print("\n%-28s %-18s %10s %10s %8s  %s" % ("layer", "prop", "design", "actual", "delta", "hint"))
        print("-" * 120)
        for r in report["diffs"]:
            print("%-28s %-18s %10s %10s %8s  %s"
                  % (str(r["layer"])[:28], r["prop"], r["design"], r["actual"], r["delta"], r["hint"][:40]))
    else:
        print("\n四个属性全部对齐。")
    sys.exit(1 if report["diffs"] else 0)


if __name__ == "__main__":
    main()
