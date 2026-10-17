# -*- coding: utf-8 -*-
"""把 index_data.json 注入 kmerge_template.html，产出单文件工具。

用法：
    python scripts/build_kmerge.py                    # 默认输出到本仓库根目录
    python scripts/build_kmerge.py --data <json> --out <html>

路径全部相对本仓库根目录解析，可整仓 clone 后直接跑。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # chanlun-kmerge/
TPL = ROOT / "templates" / "kmerge_template.html"

ap = argparse.ArgumentParser()
ap.add_argument("--data", default=None, help="index_data.json 路径")
ap.add_argument("--out", default=None, help="输出的单文件 HTML 路径")
ap.add_argument("--tpl", default=None, help="模板路径")
a = ap.parse_args()

TPL = Path(a.tpl) if a.tpl else TPL
DATA = Path(a.data) if a.data else ROOT / "data" / "index_data.json"
OUT = Path(a.out) if a.out else ROOT / "缠论K线合并练习.html"

for label, p in (("模板", TPL), ("数据", DATA)):
    if not p.exists():
        sys.exit(f"缺少{label}：{p}\n先跑 scripts/fetch_index_daily.py 生成数据。")

tpl = TPL.read_text(encoding="utf-8")
payload = DATA.read_text(encoding="utf-8")

# 防注入：JSON 里不能出现会提前闭合 script 标签的片段
for bad in ("</script", "<!--"):
    if bad in payload:
        sys.exit(f"数据中含危险片段 {bad}")

if "__DATA__" not in tpl:
    sys.exit("模板缺少 __DATA__ 占位符")

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(tpl.replace("__DATA__", payload), encoding="utf-8")

j = json.loads(payload)
rows = {k: len(v["rows"]) for k, v in j["indices"].items()}
print(f"写出 {OUT}  ({OUT.stat().st_size/1024:.1f} KB)")
print(f"数据 meta: {j['meta']}")
print(f"内置指数 {len(rows)} 个: {rows}")
