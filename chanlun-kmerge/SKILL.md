---
name: chanlun-kmerge
description: |
  生成一个离线的「缠论 K 线合并练习工具」单文件 HTML：内置 7 个 A 股指数的真实日线
  数据（2005 年至今），把 K 线画成光头光脚实体（无影线，区间一眼可见），让学习者点一根
  K 线 → 自动选中它与右邻一根 → 按缠论原文的包含处理规则合并，并在合并前校验「是否真的
  构成包含」「手动指定的方向是否正确」，另有「完成检查」按钮全区间扫描剩余包含关系。
  Use when the user wants to practise 缠论 K 线包含处理 / 分型 / 合并 ("练缠论包含处理",
  "缠论练习工具", "K线合并练习", "画缠论练习图"), or wants to regenerate the tool with
  fresher index data. Do NOT use for: 自动生成买卖点、选股、回测、实盘信号 —— 本工具只做
  合并处理的手工练习，不产生任何交易结论。
---

# 缠论 K 线合并练习工具

## 这是什么

一个自包含的单文件 HTML（`缠论K线合并练习.html`，约 1.8 MB）。数据直接内嵌，双击
`file://` 打开即可用，不需要服务器、不联网、不装任何东西。

练习的是缠论的**包含处理**：相邻两根 K 线区间互相罩住时，必须按当前处理方向合并成一根。

## 规则实现（缠论原文，必须严格照此）

### 方向判定

要合并 `b、c`（b 左 c 右），参照物 `a = b 左边那根「与 b 无包含关系」的 K 线`：

- `g_b > g_a`（b 的高点高于 a）→ **向上处理**
- `d_b < d_a`（b 的低点低于 a）→ **向下处理**

两个原文级别的细节：

- **a 必须与 b 无包含**。若 a 与 b 本身构成包含，a 没资格当参照，继续往左找，直到找到
  无包含的那根。原文逻辑是：`g_n ≥ g_{n-1}` 且 `d_n ≤ d_{n-1}` 不可能同时成立，否则
  n 与 n-1 本身就是包含，必须先处理更前面那对。
- **用严格不等号**。原文写的 `≥` / `≤` 普遍认为是笔误 —— 如果高点相等，两根 K 线一端
  平齐，无论另一端怎样都必然构成包含，与「n 与 n-1 不包含」的前提矛盾。实务遇到
  等高 / 等低，方向延续更早的判定即可。

方向**逐次重新判定**。顶部「自动 / 向上 ⇅ / 向下 ⇇」可手动覆盖（`D` 键循环）。

### 合并

| 处理方向 | 新 K 线高点 | 新 K 线低点 | 口诀 |
|---|---|---|---|
| 向上 | 两根中**较高**的高 | 两根中**较高**的低 | 高高（阳线） |
| 向下 | 两根中**较低**的高 | 两根中**较低**的低 | 低低（阴线） |

注意反直觉处：向上处理时**低点也取"较高"的**（整体上抬）；向下处理时**高点也取"较低"的**
（整体下压）。四个值都往方向那一侧收，不是"向上 = 都取最大值"。

等价 2×2 表：

| 包含 | 向上(高高) | 向下(低低) |
|---|---|---|
| 左包右 | 高←左、低←右 | 高←右、低←左 |
| 右包左 | 高←右、低←左 | 高←左、低←右 |

### 渲染：光头光脚

实体矩形从最高价一直画到最低价，**完全不画上下影线**。开收盘只决定颜色（阳红阴绿），
不影响形状 —— 缠论只关心高低点，这样相邻 K 线的包含关系一眼可见。合并产物同样光头
光脚，实体正好等于规则算出的 `[低, 高]`：向上 → 开=低、收=高（阳）；向下 → 开=高、
收=低（阴）。

## 工具自带的两个校验

1. **合并前校验**（`doMerge` 开头调 `checkMergeable`）
   - 是否存在包含关系 —— 没有包含就合并等于把两根无关 K 线凭空捏成一根，**必拒**。
   - 方向是否正确 —— **只有手动模式才校验**（自动模式下方向由程序算出，不存在选错）。
     手动选的方向必须和规则判定一致，否则拒绝并给出正确方向 + 依据（a 是哪根、
     `g_b/g_a` 或 `d_b/d_a` 的比较）。
   - 若 b 左侧找不到任何合格参照物，方向只能靠延续、判不出对错，此时**不拦**。
   - 被拒时 pill 转红抖动成「✗ 不可合并」，上方弹出多行说明框。
2. **完成检查**（`doDone` / `F` 键）
   - 扫描相邻包含关系。范围**默认「视窗内」**（当前 60/90/120/250/500/1000 根，这才是
     正在练的区段）；旁边「范围：视窗内 / 全序列」可切到全序列（2005 年至今全部）。
   - 还有剩余 → 红框列出未处理的相邻对、各自应按高高还是低低，并**自动定位到第 1 处**。
   - 已清空 → 绿框确认；若只是视窗内清空，还会提示视窗外还有多少处。

> ⚠️ **别把范围写成全序列**：早期版本硬编码扫全序列，在只显示 120 根时按钮报「剩 1169」，
> 与用户眼前的画面完全对不上。范围必须跟着视窗走，并在滚轮缩放 / 平移 / 合并 / 撤销 /
> 切指数后重算。

## 文件

```
缠论K线合并练习.html      构建产物，自包含（数据已内嵌），直接双击打开
templates/
  kmerge_template.html    源码模板，含 __DATA__ 占位符  ← 改这个
scripts/
  fetch_index_daily.py    拉 7 指数日线 OHLC（新浪源）+ 交叉校验 → data/index_data.json
  build_kmerge.py         注入数据生成单文件 HTML
data/
  index_data.json         缓存的数据快照（克隆后可直接构建，无需联网）
  index_daily/*.csv       各指数 OHLC CSV
tests/
  test_merge_rule.js      8 场景：方向判定 / 高高低低 / 光头光脚 / 无参照
  test_check_rule.js      31 项：合并前校验 / 完成检查范围
  verify_built.js         从产物 HTML 里抽函数跑，7 指数 6688 个包含对全量复验
  check_refs.js           构建期校验 JS 控件引用 vs HTML id（防 null.children 白屏）
```

## 怎么改

**改渲染 / 交互 / 规则** → 改 `templates/kmerge_template.html`，然后：

```powershell
$py = "$env:USERPROFILE\miniconda3\python.exe"   # 需要 requests；默认 python venv 没有
& $py -B scripts/build_kmerge.py
```

**更新指数数据**（拉到最新交易日）：

```powershell
& $py -B scripts/fetch_index_daily.py            # 主源新浪，自动重试 4 次
& $py -B scripts/build_kmerge.py
```

可选 `--cache <csv>` 传入本地 close 缓存做交叉校验；`--start 2015-01-01` 缩小起始日期。

## 改完必须跑测试

测试脚本从**目标文件**里用正则抽出真实函数再 `eval`，所以测的是产物本身，不是抄一份：

```powershell
node tests/check_refs.js templates/kmerge_template.html   # 控件引用
node tests/test_merge_rule.js                             # 合并规则
node tests/test_check_rule.js                             # 校验 + 范围
node tests/verify_built.js                                # 产物全量复验
```

四条都必须 ALL PASS / RESOLVE。`check_refs.js` 里的 `DYNAMIC` 白名单列出了运行时用
`document.createElement` 动态挂载、不在静态 HTML 里的控件（`toast`、`note`）—— 新增
同类控件时要补进去，否则会误报 MISSING。

## 数据来源与校验

主源 `money.finance.sina.com.cn CN_MarketData.getKLineData`。

降级链实测记录（2026-10-17）：
1. 本地缓存 `stock-analyzer\data\kline_8y\_sh000001.csv` —— 只有 date+close，无 OHLC，仅用于交叉校验
2. tinyshare `pro.index_daily` —— 积分授权码已过期（`TinySharePermissionError`）
3. akshare `stock_zh_index_daily_em` —— 首次成功拉全量 8743 根，之后连续请求被东财 `RemoteDisconnected` 限流
4. 新浪 —— 可用，本项目采用

指数无需复权。已做的校验：`l <= o,c <= h` 合法性、与本地缓存 1962 个收盘价比对全部
一致、与东财 akshare 独立取的 6 根 OHLC 比对全部一致。

内置 7 个指数：上证指数 5289 根 / 深证成指 5289 / 创业板指 3975 / 沪深300 5289 /
中证500 5289 / 科创50 1643 / 上证50 5289，均为 2005-01-01 起。周 K 由日 K 聚合（1110 根）。

## 已知坑

- **不要用 `--directory` 之外的方式起服务测中文文件名**：内置 Browser 用 `http://`
  访问中文文件名会 404，测试时复制成 ASCII 名（如 `_t.html`）再访问，**测完删掉**。
- **截图像素 ≠ 真实视口**：内置 Browser 的截图是 2× 缩放（截图 1478 宽 vs 实际视口
  739 宽）。canvas 点击坐标必须取自 `inspect` 给的真实 `rect`，按截图像素算会点偏好几根 K 线。
- **`localStorage` 在 `file://` 可能被禁**：`save()` / `loadState()` 都有 try/catch，
  禁了就退化成不保存，不要因为没 try/catch 导致整页白屏。
- **`draw()` 里任何异常都会静默吃掉整帧**（框画出来但 pill 消失）。`draw()` 已包
  try/catch，但新增绘制代码后要实测一遍，别只看代码。
- **中文输出到 PowerShell 控制台是 GBK 乱码**，不是脚本坏了。加
  `[Console]::OutputEncoding=[Text.Encoding]::UTF8` 或用 `-Encoding UTF8` 读文件。
