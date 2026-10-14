#!/usr/bin/env python3
"""Historical daily K-line smoke test; Tencent endpoints adapted from simonlin1212/a-stock-data."""
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HOSTS = ["https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com/ifzqgtimg", "https://ifzq.gtimg.cn"]
SYMBOLS = ["sh600519", "sz000001", "sh601318", "sz300750", "sz300308",
           "sh600036", "sz002594", "sh601012", "sh688981", "sz000858"]
OUT = Path("data")
OUT.mkdir(exist_ok=True)

def fetch(symbol, count=120):
    param = f"{symbol},day,,,{count},qfq"
    errors = []
    for host in HOSTS:
        url = host + "/appstock/app/fqkline/get?" + urlencode({"param": param})
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
            with urlopen(req, timeout=22) as response:
                payload = json.load(response)
            node = payload.get("data", {}).get(symbol, {})
            # Never silently substitute raw prices when an explicitly returned qfqday is empty.
            bars = node.get("qfqday", node.get("day"))
            if not isinstance(bars, list) or len(bars) < 20:
                raise ValueError(f"invalid or insufficient bars: {len(bars) if isinstance(bars, list) else 'missing'}")
            rows = []
            for b in bars:
                day = datetime.strptime(str(b[0]), "%Y-%m-%d").date().isoformat()
                o, c, h, l, vol = map(float, b[1:6])
                if not (0 < l <= min(o, c) <= max(o, c) <= h and vol >= 0):
                    raise ValueError(f"invalid OHLCV {symbol} {day}")
                rows.append(dict(symbol=symbol, date=day, open=o, high=h, low=l, close=c, volume=vol,
                                 volume_unit="shares" if symbol.startswith(("sh688", "sh689")) else "lots",
                                 adjustment="qfq", source_host=host))
            if len({r["date"] for r in rows}) != len(rows):
                raise ValueError("duplicate dates")
            rows.sort(key=lambda r: r["date"])
            if rows[-1]["date"] > datetime.now(timezone.utc).date().isoformat():
                raise ValueError("future date")
            for i, row in enumerate(rows):
                for n in (5, 10, 20):
                    row[f"ma{n}"] = round(sum(r["close"] for r in rows[i-n+1:i+1])/n, 4) if i >= n-1 else ""
            return rows
        except Exception as exc:
            errors.append(f"{host}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))

def main():
    all_rows, failures = [], {}
    for symbol in SYMBOLS:
        try:
            rows = fetch(symbol)
            all_rows.extend(rows)
            print(f"OK {symbol}: {len(rows)} bars, {rows[0]['date']} to {rows[-1]['date']}, {rows[-1]['source_host']}", flush=True)
        except Exception as exc:
            failures[symbol] = str(exc)
            print(f"FAIL {symbol}: {exc}", flush=True)
        time.sleep(0.8)
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "requested_symbols": SYMBOLS,
              "successful_symbols": sorted({r["symbol"] for r in all_rows}), "failures": failures,
              "rows": len(all_rows), "note": "Tencent qfq daily K-lines; no turnover amount. Volume units differ for STAR Market."}
    (OUT / "fetch_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if all_rows:
        with (OUT / "sample_daily_120.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
    if failures:
        raise SystemExit(f"{len(failures)} of {len(SYMBOLS)} symbols failed; see report and workflow logs")
    print("PASS: all 10 symbols fetched and validated", flush=True)

if __name__ == "__main__":
    main()
