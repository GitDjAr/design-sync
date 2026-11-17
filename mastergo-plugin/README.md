# Design Spec Export — MasterGo 插件

直读设计稿属性，导出成 `mgspec/compare.py` 和 `mgspec/server.py` 能直接吃的 JSON。
**不经过 Sketch/Figma 转换，不存在导出变形问题。**

## 装

1. MasterGo 里打开任意设计文件
2. 菜单 → 插件 → 开发插件 → 创建/添加插件
3. 选这个目录下的 `manifest.json`
4. 插件会出现在插件列表里，点开右侧面板

`manifest.json` 里的 `"api": "1.0.0"` 不能改，改了加载不了。

## 用

面板上三个按钮：

| 按钮 | 范围 |
|---|---|
| 导出当前页 | 当前 page 全部可见图层 |
| 导出选中 | 只导当前选中的图层（推荐，token 省一半以上） |
| 含隐藏 | 当前页，连隐藏图层一起（排查"为什么实现端多了一块"用） |

导出后：

- 左上是统计：图层数 / 带圆角 / 带自动布局 / 文本数 / 隐藏数 / 耗时
- 中间两个视图切换：**AI 文本**（紧凑，直接粘给 AI）和 **spec JSON**（完整，存文件）
- 底部：复制当前视图 / 下载 `.spec.json`

下载被宿主拦截时用「复制当前视图」，粘进 `design.spec.json` 一样能用。

## 输出结构

和 `sketch_reader.py` 完全一致，所以下游零改动：

```json
{
  "source": "mastergo-plugin",
  "kind": "plugin",
  "meta": { "page": "首页", "scope": "page" },
  "pages": [{
    "page": "首页",
    "nodes": [{
      "uid": "12:34",
      "parent": "12:1",
      "path": "首页/优惠券卡片",
      "name": "优惠券卡片",
      "type": "FRAME",
      "frame": { "x": 16, "y": 24, "w": 343, "h": 120 },
      "visible": true,
      "cornerRadius": { "all": 12, "tl": 12, "tr": 12, "br": 12, "bl": 12 },
      "layout": {
        "axis": "row",
        "padding": { "top": 16, "right": 20, "bottom": 16, "left": 20 },
        "gap": 8,
        "alignItems": "center",
        "justifyContent": "flex-start"
      },
      "text": {
        "string": "优惠券",
        "fontFamily": "PingFangSC-Regular",
        "fontSize": 16,
        "lineHeight": 22,
        "lineHeightAuto": false,
        "letterSpacing": 0,
        "textAlign": "center"
      },
      "style": { "fills": [{ "color": "#FFFFFF", "type": "SOLID" }], "borders": [] },
      "absoluteBoundingBox": { "x": 16, "y": 24, "w": 343, "h": 120 }
    }]
  }]
}
```

关键字段和 CSS 的对应：

| 设计字段 | CSS |
|---|---|
| `cornerRadius.all` / `tl/tr/br/bl` | `border-radius`（四角不等时别写简写） |
| `layout.padding` | `padding` |
| `layout.gap` | `gap`（**不要用 margin 实现**） |
| `layout.axis: row/column` | `flex-direction` |
| `text.fontSize` | `font-size` |
| `text.lineHeight` | `line-height`（给 px，别写倍数） |
| `visualPadding` / `visualGap` | 手动摆放的节点，靠这两个反推间距 |

## 接现有链路

```bash
# 把导出的文件丢进 designs/
mv ~/Downloads/首页.spec.json designs/home.spec.json

# 直接对账
python3 mgspec/compare.py designs/home.spec.json page.computed.json

# 或者让 AI 通过自建 MCP 服务查
python3 mgspec/server.py mcp --root ./designs
```

`designs/*.sketch` 和 `designs/*.mg` 在 `.gitignore` 里，但 `.spec.json` 不在 —— 只有文本，
可以放心提交，当版本基线用。

## 常见问题

**导出的图层比画布上少**
默认只导可见图层。用「含隐藏」。

**没有自动布局的节点，padding 全是 0**
那是手动摆放的卡片，本来就没有 padding 概念。看 `visualPadding` 和 `visualGap`，
这俩是从绝对坐标反推的视觉距离，实现时用 padding + gap 复现。

**字体读不到 / fontSize 是 null**
`fontName` 是 mixed（同一文本块里混了多种样式）。这种节点回 MasterGo 单独看，
插件已经跳过不报错。

**节点太多卡住**
面板会显示"已遍历 N 个图层"。超大页面先用「导出选中」，选中一个模块导一次。

**想改字段**
`main.js` 里 `makeNodeRec()` 是唯一出口，加字段在那里加；
`ui.html` 不用动，它只是把 JSON 显示出来。
