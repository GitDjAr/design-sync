#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mg_reader.py — 读 MasterGo 原生 .mg 文件。

已知结构（社区逆向，见 AaronXu-Lab/MasterGo2Figma/docs/MG_DECODER.md）：
    .mg = zip { document, meta.json, images/ }
    document 是 MasterGo 私有二进制串行化结果；
    其中"部分"节点附带 injected v2-JSON 片段（Figma 风格的属性 JSON），
    形如 [{"id":..,"name":..,"cornerRadius":..,"paddingLeft":..,"fontSize":..}, ...]

所以本脚本走两条路：
  1) 主流：从 document 二进制里把 v2-JSON 片段全部捞出来（括号配平 + json.loads 校验）
  2) 兜底：对局部结构做正则抽取（只有个别节点有 JSON 时用）

注意（很重要，直接影响 margin/padding 判断）：
  - 完整编辑器导出的 .mg：缺失的 padding / itemSpacing 默认值是 **10**
  - 分享/部分导出（share mode）的 .mg：默认值是 **0**
  这解释了"设计稿明明没设间距，实现端却差了 10px"这类幽灵差异。
  本脚本在输出里显式标注 defaultPaddingAssumed。

用法：
    python3 mg_reader.py a.mg -o a.spec.json
    python3 mg_reader.py a.mg --probe          # 只看容器结构，不解码
    python3 mg_reader.py a.mg --ai
"""
import argparse
import json
import os
import re
import sys
import zipfile

MG_KEYS = (
    "cornerRadius", "topLeftRadius", "paddingLeft", "paddingTop", "itemSpacing",
    "fontSize", "lineHeight", "letterSpacing", "absoluteBoundingBox", "layoutMode",
)


# ---------------------------------------------------------------- zip
def open_mg(path):
    if not zipfile.is_zipfile(path):
        raise SystemExit(
            "%s 不是 zip。MasterGo 老版本/分享链接下的 .mg 可能是纯二进制，"
            "先试 `file %s` 和 `xxd -l 32 %s`" % (path, path, path)
        )
    zf = zipfile.ZipFile(path)
    return zf, zf.namelist()


def read_document(zf, names):
    for cand in ("document", "document.json", "doc"):
        if cand in names:
            return cand, zf.read(cand)
    # 退路：最大的非 images 条目
    best = None
    for n in names:
        if n.startswith("images/"):
            continue
        info = zf.getinfo(n)
        if best is None or info.file_size > best[1]:
            best = (n, info.file_size)
    if best is None:
        raise SystemExit("zip 里找不到 document 条目")
    return best[0], zf.read(best[0])


# ---------------------------------------------------------------- json harvest
def harvest_json_blobs(buf):
    """
    在二进制里找出所有可解析的 JSON 对象/数组片段。
    用括号配平状态机（处理字符串与转义），比正则可靠。
    """
    blobs = []
    i, n = 0, len(buf)
    start_chars = (0x7B, 0x5B)  # { [
    while i < n:
        if buf[i] not in start_chars:
            i += 1
            continue
        depth, in_str, esc, j = 0, False, False, i
        while j < n:
            c = buf[j]
            if in_str:
                if esc:
                    esc = False
                elif c == 0x5C:  # backslash
                    esc = True
                elif c == 0x22:  # "
                    in_str = False
            else:
                if c == 0x22:
                    in_str = True
                elif c in (0x7B, 0x5B):
                    depth += 1
                elif c in (0x7D, 0x5D):
                    depth -= 1
                    if depth == 0:
                        break
            j += 1
        if depth == 0 and j > i + 8:
            chunk = buf[i:j + 1]
            if _looks_json(chunk):
                try:
                    obj = json.loads(chunk.decode("utf-8", "strict"))
                    if _is_useful(obj):
                        blobs.append(obj)
                    i = j + 1
                    continue
                except Exception:
                    pass
        i += 1
    return blobs


def _looks_json(chunk):
    return b'"' in chunk and (b":" in chunk)


def _is_useful(obj):
    """过滤掉 {a:1} 这种噪声，只要带设计属性的对象。"""
    if isinstance(obj, list):
        return any(_is_useful(x) for x in obj[:50])
    if not isinstance(obj, dict):
        return False
    if any(k in obj for k in MG_KEYS):
        return True
    return False


def flatten_nodes(objs):
    """把 {} 与 [] 混合的结构拍平成节点列表。"""
    nodes = []
    seen = set()

    def rec(o, depth=0):
        if depth > 400:
            return
        if isinstance(o, list):
            for x in o:
                rec(x, depth + 1)
            return
        if not isinstance(o, dict):
            return
        if any(k in o for k in MG_KEYS) or ("id" in o and "name" in o):
            key = (str(o.get("id")), str(o.get("name")), id(o))
            if key not in seen:
                seen.add(key)
                nodes.append(o)
        for v in o.values():
            if isinstance(v, (dict, list)):
                rec(v, depth + 1)

    for o in objs:
        rec(o)
    return nodes


# ---------------------------------------------------------------- normalize
ALIGN_TOK = {"MIN": "flex-start", "MAX": "flex-end", "CENTER": "center", "SPACE_BETWEEN": "space-between"}


def normalize(node, idx):
    bb = node.get("absoluteBoundingBox") or {}
    out = {
        "uid": "mg%d" % idx,
        "name": node.get("name"),
        "type": node.get("type"),
        "frame": {
            "x": bb.get("x"), "y": bb.get("y"),
            "w": bb.get("width", node.get("width")),
            "h": bb.get("height", node.get("height")),
        },
    }
    # 圆角：四角独立 or 统一
    if any(k in node for k in ("cornerRadius", "topLeftRadius", "topRightRadius")):
        out["cornerRadius"] = {
            "all": node.get("cornerRadius"),
            "tl": node.get("topLeftRadius", node.get("cornerRadius")),
            "tr": node.get("topRightRadius", node.get("cornerRadius")),
            "br": node.get("bottomRightRadius", node.get("cornerRadius")),
            "bl": node.get("bottomLeftRadius", node.get("cornerRadius")),
        }
    # 自动布局
    if node.get("layoutMode") in ("HORIZONTAL", "VERTICAL"):
        out["layout"] = {
            "axis": "row" if node["layoutMode"] == "HORIZONTAL" else "column",
            "padding": {
                "top": node.get("paddingTop", 0),
                "right": node.get("paddingRight", 0),
                "bottom": node.get("paddingBottom", 0),
                "left": node.get("paddingLeft", 0),
            },
            "gap": node.get("itemSpacing", 0),
            "counterGap": node.get("counterAxisSpacing"),
            "alignItems": ALIGN_TOK.get(str(node.get("counterAxisAlignItems")), node.get("counterAxisAlignItems")),
            "justifyContent": ALIGN_TOK.get(str(node.get("primaryAxisAlignItems")), node.get("primaryAxisAlignItems")),
        }
    # 文本
    st = node.get("style") or {}
    if node.get("characters") is not None or st.get("fontSize"):
        out["text"] = {
            "string": (node.get("characters") or "")[:200],
            "fontFamily": st.get("fontFamily") or st.get("fontPostScriptName"),
            "fontSize": st.get("fontSize"),
            "lineHeight": (st.get("lineHeightPx") or st.get("lineHeight")),
            "lineHeightUnit": st.get("lineHeightUnit"),
            "letterSpacing": st.get("letterSpacing"),
            "textAlign": st.get("textAlignHorizontal"),
            "fontWeight": st.get("fontWeight"),
        }
    return out


def read_mg(path):
    zf, names = open_mg(path)
    doc_name, buf = read_document(zf, names)
    blobs = harvest_json_blobs(buf)
    nodes_raw = flatten_nodes(blobs)
    nodes = [normalize(n, i) for i, n in enumerate(nodes_raw)]
    zip_names = names

    coverage = None
    if nodes:
        total = len(nodes)
        with_radius = sum(1 for n in nodes if "cornerRadius" in n)
        with_pad = sum(1 for n in nodes if n.get("layout"))
        with_text = sum(1 for n in nodes if n.get("text"))
        coverage = {"nodes": total, "radius": with_radius, "autolayout": with_pad, "text": with_text}

    return {
        "source": os.path.basename(path),
        "kind": "mg",
        "container": {"document": doc_name, "bytes": len(buf), "zipEntries": len(zip_names),
                      "images": sum(1 for n in zip_names if n.startswith("images/"))},
        "jsonBlobs": len(blobs),
        "coverage": coverage,
        "defaultPaddingAssumed": 10,
        "notes": [
            "完整编辑器导出的 .mg 缺省 padding/itemSpacing 视为 10；share/部分导出视为 0。",
            "老版本/分享链接的 .mg 可能完全不含 v2-JSON，此时本脚本只能捞到少量节点，"
            "请改用 MasterGo2Figma 的原生解码器转出完整 JSON。",
        ],
        "pages": [{"page": "(mg)", "nodes": nodes}],
    }


def to_ai_text(spec):
    out = []
    for pg in spec["pages"]:
        for n in pg["nodes"]:
            bits = ["[%s] %s" % (n.get("type"), n.get("name"))]
            f = n["frame"]
            if f.get("w") is not None:
                bits.append("%gx%g" % (f["w"] or 0, f["h"] or 0))
            c = n.get("cornerRadius")
            if c:
                bits.append("radius %s" % (c["all"] if c["all"] is not None
                                           else "%s/%s/%s/%s" % (c["tl"], c["tr"], c["br"], c["bl"])))
            L = n.get("layout")
            if L:
                p = L["padding"]
                bits.append("pad(t%s r%s b%s l%s) gap %s" % (p["top"], p["right"], p["bottom"], p["left"], L["gap"]))
            t = n.get("text")
            if t and (t.get("fontSize") or t.get("string")):
                bits.append("text %r %s %s" % (t["string"][:40], t.get("fontFamily"), t.get("fontSize")))
            out.append("  " + " | ".join(bits))
    return "\n".join(out)


def probe(path):
    zf, names = open_mg(path)
    doc_name, buf = read_document(zf, names)
    print("zip entries :", len(names))
    for n in names[:40]:
        print("   -", n, zf.getinfo(n).file_size)
    print("document    :", doc_name, len(buf), "bytes")
    print("magic       :", buf[:8].hex())
    print("has v2-JSON :", b'"cornerRadius"' in buf or b'"paddingLeft"' in buf or b'"fontSize"' in buf)
    print("json blobs  :", len(harvest_json_blobs(buf)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mg")
    ap.add_argument("-o", "--out")
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    if a.probe:
        probe(a.mg)
        return
    spec = read_mg(a.mg)
    if a.ai:
        txt = to_ai_text(spec)
        (open(a.out, "w", encoding="utf-8").write(txt) if a.out else sys.stdout.write(txt))
        return
    txt = json.dumps(spec, ensure_ascii=False, indent=2)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(txt)
        sys.stderr.write("ok: %s -> %s (coverage=%s)\n" % (a.mg, a.out, spec["coverage"]))
    else:
        sys.stdout.write(txt)


if __name__ == "__main__":
    main()
