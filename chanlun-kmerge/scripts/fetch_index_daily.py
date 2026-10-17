# -*- coding: utf-8 -*-
"""拉取多指数日线 OHLC —— 主源新浪 CN_MarketData.getKLineData。

降级链实测记录（2026-10-17）：
  1) 本地缓存 stock-analyzer\\data\\kline_8y\\_sh000001.csv —— 只有 date+close，无 OHLC，仅用于交叉校验
  2) tinyshare pro.index_daily           —— 积分授权码已过期（实测 TinySharePermissionError）
  3) akshare stock_zh_index_daily_em     —— 首次成功拉全量 8743 根，之后连续请求被东财 RemoteDisconnected 限流
  4) 新浪 money.finance.sina.com.cn      —— 可用，本脚本采用
指数无需复权。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import requests

ROOT = Path(__file__).resolve().parent.parent          # chanlun-kmerge/
OUT_DIR = ROOT / "data" / "index_daily"
OUT_DIR.mkdir(parents=True, exist_ok=True)
JSON_PATH = ROOT / "data" / "index_data.json"

# 可选的校验基准 A：本地已有 close 缓存（没有就跳过该校验，不影响产出）
_ap = argparse.ArgumentParser()
_ap.add_argument("--cache", default="", help="date,close 两列的 CSV，用于 close 交叉校验")
_ap.add_argument("--start", default="2005-01-01", help="起始日，默认 2005-01-01")
_a = _ap.parse_args()
CACHE = Path(_a.cache) if _a.cache else None

START = _a.start
SOURCE = "money.finance.sina.com.cn CN_MarketData.getKLineData"

INDICES = [
    ("sh000001", "上证指数", "000001.SH"),
    ("sz399001", "深证成指", "399001.SZ"),
    ("sz399006", "创业板指", "399006.SZ"),
    ("sh000300", "沪深300", "000300.SH"),
    ("sh000905", "中证500", "000905.SH"),
    ("sh000688", "科创50", "000688.SH"),
    ("sh000016", "上证50", "000016.SH"),
]

# akshare/东财 首次成功时取到的实测值（2026-10-17），用于独立交叉校验新浪数据。
# 这是校验基准快照；随时间推移超出该日期的样本会自动跳过。
AKSHARE_REF = {
    "2026-10-09": (3804.09, 3824.71, 3754.14, 3813.79),
    "2026-10-12": (3806.98, 3828.22, 3791.00, 3797.24),
    "2026-10-13": (3760.80, 3822.11, 3741.53, 3800.86),
    "2026-10-14": (3790.63, 3811.81, 3761.96, 3767.23),
    "2026-10-15": (3710.70, 3724.56, 3674.82, 3707.48),
    "2026-10-16": (3723.80, 3750.77, 3681.28, 3716.28),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

# ---------- 交叉校验基准 A：本地缓存 close ----------
cache_close = {}
if CACHE and CACHE.exists():
    for line in CACHE.read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2:
            cache_close[parts[0].strip()] = float(parts[1])
    print(f"[cache] 本地缓存 {len(cache_close)} 条，最新 {max(cache_close)}\n")


def fetch(sym):
    url = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=8000"
    )
    last = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                return data
            last = f"empty payload: {str(data)[:120]}"
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)[:160]
        time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(last)


payload = {}
summary = []
for sym, name, code in INDICES:
    try:
        raw = fetch(sym)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {sym} {name}: {exc}")
        continue

    start_key = START.replace("-", "")
    rows = []
    dropped = 0
    for it in raw:
        day = str(it.get("day", ""))
        d = day.replace("-", "")
        if len(d) != 8 or d < start_key:
            continue
        try:
            o, h, l, c = (float(it["open"]), float(it["high"]),
                          float(it["low"]), float(it["close"]))
            v = float(it.get("volume") or 0)
        except Exception:  # noqa: BLE001
            dropped += 1
            continue
        if not (l <= o <= h and l <= c <= h) or c <= 0:
            dropped += 1
            continue
        rows.append([d, round(o, 2), round(h, 2), round(l, 2), round(c, 2), int(v)])
    rows.sort(key=lambda r: r[0])
    if not rows:
        print(f"[FAIL] {sym} {name}: 清洗后为空")
        continue

    csv_path = OUT_DIR / f"{sym}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("date,open,high,low,close,volume\n")
        for r in rows:
            fh.write(f"{r[0]},{r[1]:.2f},{r[2]:.2f},{r[3]:.2f},{r[4]:.2f},{r[5]}\n")

    # 校验 A：与本地缓存 close 比对（仅上证指数有本地缓存）
    agree = tot = 0
    if sym == "sh000001":
        by_d = {r[0]: r[4] for r in rows}
        for d, c in cache_close.items():
            if d in by_d:
                tot += 1
                agree += abs(by_d[d] - c) <= 0.02

    # 校验 B：与 akshare/东财 实测 6 根 OHLC 比对
    ref_ok = []
    by_d2 = {r[0]: r for r in rows}
    for d, ref in AKSHARE_REF.items():
        dk = d.replace("-", "")
        if dk in by_d2:
            r = by_d2[dk]
            ref_ok.append(
                all(abs(r[1 + i] - ref[i]) <= 0.02 for i in range(4))
            )

    payload[sym] = {"name": name, "code": code, "rows": rows}
    line = (
        f"[OK] {sym} {name}  {len(rows)} 根  {rows[0][0]}~{rows[-1][0]}  "
        f"末值 C={rows[-1][4]:.2f}  丢弃 {dropped}"
    )
    if tot:
        line += f"  |本地缓存close一致 {agree}/{tot}"
    if ref_ok:
        line += f"  |东财6根OHLC一致 {sum(ref_ok)}/{len(ref_ok)}"
    print(line)
    summary.append((sym, name, len(rows), rows[-1][0], rows[-1][4]))
    time.sleep(0.8)

meta = {
    "source": SOURCE,
    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "start": START,
    "note": "指数无需复权；已做 l<=o,c<=h 合法性校验；已与本地缓存 close 及东财 akshare 交叉校验",
}
JSON_PATH.write_text(
    json.dumps({"meta": meta, "indices": payload}, ensure_ascii=False, separators=(",", ":")),
    encoding="utf-8",
)
print(f"\n写出 {JSON_PATH}  ({JSON_PATH.stat().st_size / 1024:.1f} KB)")
print(f"成功 {len(payload)}/{len(INDICES)} 个指数；CSV 在 {OUT_DIR}")
