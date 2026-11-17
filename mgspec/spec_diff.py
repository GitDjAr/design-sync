#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spec_diff.py — 比较两份设计规格，输出"设计侧改了什么"。

这是把设计变更变成可 review 的代码变更的关键一环：
插件导出的 spec.json 提交进仓库后，每次设计迭代就是一次 json diff，
实现端照着改，不用再问设计师"这版改了哪里"。

用法：
    python3 spec_diff.py old.spec.json new.spec.json
    python3 spec_diff.py old.spec.json new.spec.json --md >> CHANGELOG.md

退出码：有变更返回 1，无变更返回 0（方便挂 CI 提醒）。
"""
import argparse
import json
import sys

WATCH = [
    ("cornerRadius", lambda n: n.get("cornerRadius")),
    ("padding", lambda n: (n.get("layout") or {}).get("padding")),
    ("gap", lambda n: (n.get("layout") or {}).get("gap")),
    ("axis", lambda n: (n.get("layout") or {}).get("axis")),
    ("fontSize", lambda n: (n.get("text") or {}).get("fontSize")),
    ("lineHeight", lambda n: (n.get("text") or {}).get("lineHeight")),
    ("letterSpacing", lambda n: (n.get("text") or {}).get("letterSpacing")),
    ("box", lambda n: n.get("frame")),
    ("visible", lambda n: n.get("visible")),
]

UNIT = {
    "cornerRadius": "radius", "padding": "pad", "gap": "gap", "axis": "",
    "fontSize": "px", "lineHeight": "px", "letterSpacing": "px", "box": "box", "visible": "",
}


def key_of(n):
    """用图层路径当主键：名字稳定，位置变了也不会错配。"""
    return n.get("path") or n.get("name")


def index(spec):
    out = {}
    for pg in spec.get("pages", []):
        for n in pg.get("nodes", []):
            k = key_of(n)
            if k:
                out[k] = n
    return out


def fmt(v):
    if v is None:
        return "—"
    if isinstance(v, dict):
        if set(v) >= {"tl", "tr", "br", "bl"}:
            if v.get("all") is not None:
                return "%g" % v["all"]
            return "%g/%g/%g/%g" % (v["tl"], v["tr"], v["br"], v["bl"])
        if "top" in v:
            return "t%g r%g b%g l%g" % (v["top"], v["right"], v["bottom"], v["left"])
        if "w" in v:
            return "%gx%g" % (v["w"], v["h"])
    if isinstance(v, float) and v.is_integer():
        return "%g" % v
    return str(v)


def diff(old, new):
    a, b = index(old), index(new)
    added = [k for k in b if k not in a]
    removed = [k for k in a if k not in b]
    changed = []
    for k in b:
        if k not in a:
            continue
        for name, get in WATCH:
            va, vb = get(a[k]), get(b[k])
            if va == vb:
                continue
            if va is None and vb is None:
                continue
            changed.append({
                "layer": k,
                "prop": name,
                "old": fmt(va),
                "new": fmt(vb),
                "unit": UNIT.get(name, ""),
            })
    return {"added": added, "removed": removed, "changed": changed}


def to_md(r, old_name, new_name):
    lines = ["## %s → %s" % (old_name, new_name), ""]
    if not (r["added"] or r["removed"] or r["changed"]):
        lines.append("无变更。")
        return "\n".join(lines)
    if r["added"]:
        lines.append("**新增图层 %d**" % len(r["added"]))
        for k in r["added"][:40]:
            lines.append("- `%s`" % k)
        lines.append("")
    if r["removed"]:
        lines.append("**删除图层 %d**" % len(r["removed"]))
        for k in r["removed"][:40]:
            lines.append("- `%s`" % k)
        lines.append("")
    if r["changed"]:
        lines.append("**属性变更 %d**" % len(r["changed"]))
        lines.append("")
        lines.append("| 图层 | 属性 | 旧 | 新 |")
        lines.append("|---|---|---|---|")
        for c in r["changed"][:200]:
            lines.append("| %s | %s | %s | %s |"
                         % (c["layer"], c["prop"], c["old"], c["new"]))
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--md", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    old = json.load(open(a.old, encoding="utf-8"))
    new = json.load(open(a.new, encoding="utf-8"))
    r = diff(old, new)

    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif a.md:
        print(to_md(r, a.old, a.new))
    else:
        n = len(r["added"]) + len(r["removed"]) + len(r["changed"])
        if not n:
            print("无变更。")
            return
        print("新增 %d · 删除 %d · 属性变更 %d"
              % (len(r["added"]), len(r["removed"]), len(r["changed"])))
        for k in r["added"][:20]:
            print("  + %s" % k)
        for k in r["removed"][:20]:
            print("  - %s" % k)
        if r["changed"]:
            print()
            print("%-32s %-14s %-18s %-18s" % ("layer", "prop", "old", "new"))
            print("-" * 88)
            for c in r["changed"][:60]:
                print("%-32s %-14s %-18s %-18s"
                      % (str(c["layer"])[:32], c["prop"], c["old"], c["new"]))
    sys.exit(1 if (r["added"] or r["removed"] or r["changed"]) else 0)


if __name__ == "__main__":
    main()
