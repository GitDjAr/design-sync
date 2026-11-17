# design-sync — 不依赖 MasterGo MCP 的设计/实现一致性方案

目标：让 `border-radius` / `margin` / `padding` / `font-size` 这四类反复返工的问题，
从"人肉瞪眼比对"变成"可执行的 diff"。

## 0. 先定位 MCP 到底为什么不能用

`@mastergo/magic-mcp` 有三道硬门槛，跟你的代码无关：

| 门槛 | 要求 |
|---|---|
| 账号版本 | **团队版及以上**。个人免费版不开放 MCP |
| 文件位置 | 设计文件必须在**团队项目**里。放在「草稿」里的文件 MCP 读不到 |
| Token | 个人设置 → 安全设置 → 个人访问令牌，自己生成 |

三条都满足还报「无权限」，就是席位问题。
既然账号这条路不想碰，下面全部是**不需要 MCP、不需要企业版权限**的路径。

## 1. 通道对比

| 通道 | 需要什么 | 能拿到什么 | 推荐度 |
|---|---|---|---|
| **导出 .sketch** | 普通账号，文件 → 导出为 Sketch | 圆角(四角)、自动布局 padding、gap、字号/行高/字距，全套 | ★★★★★ |
| **插件 API 导出 JSON** | 普通账号，插件 → 开发插件 | 官方 API，全套 + 设计 token 样式 | ★★★★★ |
| 导出 .mg | 普通账号 | 私有二进制，部分节点带 v2-JSON | ★★★ |
| 研发模式 Shift+D | 免费可用（D2C PRO 需企业研发席位） | 单图层 CSS，手动复制 | ★★ |
| DevTools 抓包 | 普通账号 | 协议层原始数据 | ★★ |
| 导出 SVG | 普通账号 | 只有几何 + radius；padding 靠反推 | ★★ |
| 视觉回归截图 | 无 | 像素差异，不定位到属性 | ★★★（补充） |

**结论：`.sketch` 是性价比最高的一条，一条命令就能把整份设计稿变成 JSON。**
`.sketch` = zip + JSON：`document.json` / `meta.json` / `pages/*.json` / `images/`。

## 2. 本仓库提供什么

```
mgspec/
  sketch_reader.py   .sketch -> spec.json（含几何推导的 padding/gap）
  mg_reader.py       .mg -> spec.json（捞内嵌 v2-JSON）
  compare.py         设计规格 vs 浏览器 computed style 对账 + 根因提示
  server.py          自建服务：HTTP + MCP(stdio) 双形态
  make_fixture.py    造测试样本
  http_probe.py      HTTP 自测
  selftest.sh        一键全流程自测
capture-computed.mjs 用 Playwright 抓真实计算样式
```

零第三方依赖（Python 标准库 + Playwright 仅用于抓样式）。

### 用法

```bash
# 1. 解析设计稿
python3 mgspec/sketch_reader.py design.sketch -o design.spec.json
python3 mgspec/sketch_reader.py design.sketch --ai        # 省 token 的紧凑文本，直接喂 AI

# 2. 起自建服务（替代 MCP）
python3 mgspec/server.py http --port 4310 --root ./designs
python3 mgspec/server.py mcp  --root ./designs            # stdio，给 Cursor/Codex 用
```

HTTP 接口：

```
GET  /health
GET  /spec?path=a.sketch&format=text
GET  /find?path=a.sketch&q=button
POST /compare   {"design":"a.sketch","computed":"page.json"}
```

MCP 配置（Cursor / Codex / Claude Desktop 通用）：

```json
{
  "mcpServers": {
    "design-sync": {
      "command": "python3",
      "args": ["/abs/path/mgspec/server.py", "mcp", "--root", "/abs/path/designs"]
    }
  }
}
```

暴露三个工具：`design_spec` / `design_find` / `design_compare`。

### 3. 对账闭环

```bash
# 页面元素加 data-ds="图层名"，与设计稿图层名对齐
node capture-computed.mjs http://localhost:5173 page.json
python3 mgspec/compare.py design.spec.json page.json
```

输出：

```
Card   border-radius.tl   12.0   8.0   -4.0   border 占位后外径变大：改用 box-sizing:border-box…
Card   paddingLeft        20.0  16.0   -4.0   box-sizing:content-box 会把 padding 加在宽度外…
Title  fontSize           16.0  14.0   -2.0   字体 fallback 导致度量不同…
```

差异非 0 时退出码为 1，可以直接挂 CI。

## 4. 四个属性的真实根因清单

### border-radius
- 设计给的是**外径**。实现里 `border` + `box-sizing:content-box` 会让实际外径变大，圆角视觉上变"钝"。
- 2x 设计稿的数值必须 **÷2**；且落在 DPR=1 的屏幕上时，0.5px 会取整失真。
- 四角不等（`tl/tr/br/bl`）不要写成简写，简写按顺时针吃参数容易错位。
- `overflow:hidden` 的容器 + 子元素自己圆角 = 双重裁切，边缘会出现第二道弧。
- `border` 叠在 `border-radius` 上会吃弧：想保留弧度用 `outline` 或 `box-shadow: 0 0 0 1px`。

### padding / margin
- **设计工具里没有 margin**，只有绝对几何。工程上要决定：这个间距实现成 `padding`、`gap` 还是 `margin`——**优先 gap**，`margin + :last-child` 是返工重灾区。
- MasterGo 的自动布局 `padding` ≠ CSS `padding`（有 border 时差一层 border 宽度）。
- **缺省值陷阱**：完整编辑器导出的 `.mg`，缺失的 padding/itemSpacing 默认是 **10**；分享/部分导出默认是 **0**。这是"设计看着没间距却差 10px"的典型来源。
- `margin` 塌陷：普通流相邻块级元素的 margin 会合并，设计稿不会。flex/grid 子元素不会塌陷——又一票投给 flex。
- 负 margin 在设计稿里根本不存在，凡是实现里出现就是臆造。

### font-size
- 字体没加载 → fallback 度量不同 → 行高、换行、宽度全飘。抓样式前必须 `await document.fonts.ready`。
- `line-height` 用 **px**，不要用 `1.5` 这种倍数：设计稿给的是行盒高度。
- `rem` 基准：确认 `html { font-size }` 没被 UI 库改过（不少库会设成 62.5%）。
- `letter-spacing` 单位：设计稿常给 em，实现里 px，数值不能照抄。
- 移动端 `-webkit-text-size-adjust` 和系统字体缩放会让 14px 渲染成 15px。

## 5. `.mg` 走不通时的兜底

`.mg` 是 zip（`document` + `meta.json` + `images/`），`document` 是私有二进制。
部分节点带 injected v2-JSON，`mg_reader.py` 就捞这一部分；老版本/分享链接的文件可能一个都没有。

要给完整数据，用社区已逆好的原生解码器：

```
git clone https://github.com/AaronXu-Lab/MasterGo2Figma
python3 MasterGo2Figma/pythonParser/mg_to_zip.py 你的文件.mg out.zip
```

`out.zip` 里是一堆 JSON，字段名是 Figma 风格（`cornerRadius` / `paddingLeft` / `itemSpacing` / `fontSize`），
本仓库的 `compare.py` 和 `server.py` 直接吃得下（`load_spec` 支持 `.json`）。

## 6. 插件路线（推荐，零变形）

**已经写好了，在 [`mastergo-plugin/`](mastergo-plugin/)。** 普通账号即可加载，不需要团队版。

安装：

1. MasterGo 打开任意设计文件 → 菜单 **插件 → 开发插件 → 创建/添加插件**
2. 选 `mastergo-plugin/manifest.json`
3. 面板里三个按钮：导出当前页 / 导出选中 / 含隐藏

输出结构和 `sketch_reader.py` 完全一致，`compare.py` / `server.py` 零改动直接吃：

```bash
mv ~/Downloads/首页.spec.json designs/home.spec.json
python3 mgspec/compare.py designs/home.spec.json page.computed.json
```

面板内可以直接切「AI 文本」视图，复制粘贴给 AI；
或「下载 .spec.json」落盘当版本基线（纯文本，可以提交进仓库）。

细节见 [mastergo-plugin/README.md](mastergo-plugin/README.md)。


## 7. 落地上线顺序

1. 设计侧导一份 `.sketch` 进仓库（`designs/`），当版本基线。
2. `sketch_reader.py --ai` 生成紧凑文本，直接丢给 AI 让它写样式，比截图靠谱。
3. 页面关键元素加 `data-ds`，跑 `capture-computed.mjs` + `compare.py`。
4. 把 `compare.py` 挂进 CI，差异非 0 即失败。
5. 设计 token 收敛：把反复出现的 12/16/20/24 提成变量，让实现端没有自由发挥空间。

## 8. 「导 .sketch 会变形」是真的，但要看变的是什么

MasterGo 官方自己就把取舍写在文档里了（[导入与导出](https://mastergo.com/help/getting-started/import-export.html)）：
导出 Sketch 有两种格式，**必定丢一样东西**。

| 导出选项 | 保留什么 | 丢什么 |
|---|---|---|
| 默认格式 | 组件 ↔ 实例的关联关系 | **实例覆盖**（颜色、文字、尺寸改过的都回到主组件原样） |
| 保留实例覆盖 | 实例上的所有覆盖 | 组件关联（实例被展平成组） |

所以"变形"分三档，只有第一档会影响我们：

### A. 会影响取值的（必须防）
**实例被展平 → 组尺寸按主组件原尺寸算，而不是覆盖后尺寸。**
这时节点的 `frame` 是错的，靠几何反推的 `visualPadding` / `visualGap` 也跟着错。
圆角、字号这类直接存在节点上的属性不受影响。

→ 对策：如果设计稿大量用实例覆盖且覆盖里改了尺寸/间距，导出选**「保留实例覆盖」**；
否则选**默认格式**（保住组件主尺寸）。两者都不能全信，见下面的体检。

### B. 会让数值"看着对但排版错"的
**字体没装 → Sketch 用 fallback 度量 → 文字节点宽度变 → 自动布局外框跟着变。**
`fontSize` 数值不变，但占位尺寸不可信，`lineHeight` 可能被重算。

→ 对策：装字体，或者只信 `fontSize`/`lineHeight` 数值，不信文字节点宽高。

### C. 我们根本不关心的
颜色精度、阴影/模糊、渐变手柄、布尔运算结果、矢量网络精度、蒙版模式、混合模式。
这些在导出后一定会有偏差，但它们不在 `border-radius / padding / margin / font-size` 这条线上。

### 结论

| 用途 | 导 .sketch 行不行 |
|---|---|
| 取圆角、字号、行高 | 行，风险低 |
| 取自动布局 padding / gap | 行，前提是实例没被展平 |
| 从几何反推 margin | 有风险，实例展平的节点别信 |
| 拿它当像素级视觉基准 | 不行，用截图回归 |

### 自检：`--lint`

```bash
python3 mgspec/sketch_reader.py design.sketch --lint
```

输出统计 + 字体清单 + 风险项：

```
== stat ==
  nodes / withRadius / withAutoLayout / withText / withVisualPadding / hidden
== fonts ==
  PingFangSC-Regular  x214  [本机缺失]
== issues ==
  - [四角不等] Card radius=12/12/0/0，实现端不要写简写
  - [溢出] Button 左右 padding 合计 48 >= 宽度 40，子元素会被挤爆
  - [间距缺失] List 有 8 个子节点但 gap=0，可能是导出丢了间距
  - [字号缺失] Label fontSize=None，导出或字体样式绑定丢了
  - [宽度塌陷] Title 宽度 12.0 < 字号 16，字体可能 fallback 了
```

体检通过再拿去生成代码；报「间距缺失」「溢出」「字号缺失」的节点，回 MasterGo 手工量一次。

### 最稳的还是别转换

如果设计侧愿意装一次插件，**插件直出 JSON 是零变形路径**——数据从 MasterGo 内存里直接读，
不经过任何格式转换。完整插件在 [`mastergo-plugin/`](mastergo-plugin/)，普通账号就能加载。

## 9. 设计变更追踪（把设计迭代变成可 review 的 diff）

插件导出的 `spec.json` 是纯文本，提交进仓库后，**每次设计改版就是一次 json diff**。
不用再问设计师"这版改了哪里"。

```bash
python3 mgspec/spec_diff.py designs/home.v1.spec.json designs/home.v2.spec.json
```

```
新增 1 · 删除 0 · 属性变更 8
  + 首页/Badge

layer                     prop           old                new
----------------------------------------------------------------------------
首页/Card                 cornerRadius   12                 16
首页/Card                 padding        t16 r20 b16 l16    t20 r24 b20 l24
首页/Card                 gap            8                  12
首页/Card/Title           fontSize       16                 18
首页/Card/Title           lineHeight     22                 24
```

加 `--md` 出 markdown 表格，直接贴进 PR 描述或 CHANGELOG。
有变更退出码 1，可以挂 CI 提醒"设计稿更新了，实现端还没跟"。

按**图层路径**匹配，图层改名才算新增/删除，挪位置不会错配。

推荐节奏：

1. 插件导出 → `designs/<页面>.spec.json` → 提交
2. 设计改版后重导一份 → `spec_diff` 出变更清单
3. 只改清单里那几个数值，不用重看整份设计稿

## 自测

```bash
bash mgspec/selftest.sh
```

会依次验证：样本生成 → 解析 → 导出体检 → 对账 → HTTP 服务 → MCP stdio。
