#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_fixture.py — 造一个最小 .sketch 样本，用来验证 sketch_reader / compare 能跑通。
不依赖设计工具，纯写 zip。

    python3 make_fixture.py            # 生成 fixture.sketch
    python3 sketch_reader.py fixture.sketch --ai
"""
import json
import uuid
import zipfile

def text_layer(name, s, size, lh, x, y, w=120, h=24):
    return {
        "_class": "text",
        "name": name,
        "frame": {"_class": "rect", "x": x, "y": y, "width": w, "height": h},
        "attributedString": {
            "_class": "attributedString",
            "string": s,
            "attributes": [{
                "_class": "stringAttribute",
                "location": 0,
                "length": len(s),
                "attributes": {
                    "MSAttributedStringFontAttribute": {
                        "_class": "fontDescriptor",
                        "attributes": {"name": "PingFangSC-Regular", "size": size},
                    },
                    "paragraphStyle": {"_class": "paragraphStyle",
                                       "maximumLineHeight": lh, "minimumLineHeight": lh,
                                       "alignment": 2},
                },
            }],
        },
    }

page = {
    "_class": "page",
    "name": "Page 1",
    "layers": [{
        "_class": "artboard",
        "name": "首页",
        "frame": {"_class": "rect", "x": 0, "y": 0, "width": 375, "height": 400},
        "layers": [{
            "_class": "group",
            "name": "Card",
            "frame": {"_class": "rect", "x": 16, "y": 24, "width": 343, "height": 120},
            "fixedRadius": 12,
            "groupLayout": {
                "_class": "MSImmutableStackLayout",
                "axis": 0,
                "paddingTop": 16, "paddingRight": 20,
                "paddingBottom": 16, "paddingLeft": 20,
                "itemSpacing": 8,
            },
            "style": {"_class": "style", "fills": [{"fillType": 0, "isEnabled": True,
                                                    "color": {"red": 1, "green": 1, "blue": 1, "alpha": 1}}]},
            "layers": [
                text_layer("Title", "优惠券", 16, 22, 0, 0),
                text_layer("Sub", "满100减20", 14, 20, 0, 30),
            ],
        }, {
            "_class": "rectangle",
            "name": "Avatar",
            "frame": {"_class": "rect", "x": 16, "y": 176, "width": 48, "height": 48},
            "fixedRadius": 24,
            "isVisible": True,
        }],
    }],
}

meta = {"appVersion": "test", "fonts": ["PingFangSC-Regular"],
        "pagesAndArtboards": {str(uuid.uuid4()): {"name": "Page 1", "artboards": {}}}}

with zipfile.ZipFile("fixture.sketch", "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("document.json", json.dumps({"_class": "document", "pages": []}))
    z.writestr("meta.json", json.dumps(meta))
    z.writestr("user.json", json.dumps({"document": {"pageListHeight": 85}}))
    z.writestr("pages/%s.json" % uuid.uuid4(), json.dumps(page))
print("fixture.sketch written")
