#!/usr/bin/env python3
"""A-share market discovery + bounded historical-data pilot.

Public Eastmoney security list; Tencent adjusted daily K-lines. No paid credentials.
Fails closed if universe cannot be discovered; never reports partial coverage as full.
"""
import csv
import gzip
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path("data/market")
ROOT.mkdir(parents=True, exist_ok=True)
HOSTS = ["https://web.ifzq.gtimg.cn", "https://proxy.finance.qq.com/ifzqgtimg", "https://ifzq.gtimg.cn"]
MAX_SYMBOLS = max(1, int(os.getenv("MAX_SYMBOLS", "100")))
WORKERS = min(8, max(1, int(os.getenv("WORKERS", "4"))))
COUNT = 120

def get_json(url, timeout=18):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8-sig")
    if raw.startswith("jQuery") or raw.startswith("jsonp"):
        raw = raw[raw.find("(")+1:raw.rfind(")")]
    return json.loads(raw)

def discover():
    # SH main/STAR, SZ main/ChiNext. BSE deliberately excluded for Tencent compatibility.
    fs = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
    result = {}
    for page in range(1, 100):
        params = {"pn":page, "pz":500, "po":1, "np":1, "fltt":2,
                  "invt":2, "fid":"f12", "fs":fs, "fields":"f12,f13,f14"}
        url = "https://push2.eastmoney.com/api/qt/clist/get?" + urlencode(params)
        payload = None
        for attempt in range(3):
            try:
                payload = get_json(url)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(1.5*(attempt+1))
        data = payload.get("data") or {}
        items = data.get("diff") or []
        if isinstance(items, dict):
            items = list(items.values())
        for item in items:
            code = str(item.get("f12", ""))
            market = str(item.get("f13", ""))
            if len(code) != 6 or not code.isdigit() or market not in ("0", "1"):
                continue
            if market == "1" and not code.startswith(("60", "68")):
                continue
            if market == "0" and not code.startswith(("00", "30")):
                continue
            symbol = ("sh" if market == "1" else "sz") + code
            result[symbol] = {"symbol":symbol, "name":str(item.get("f14") or "")}
        total = int(data.get("total") or 0)
        if not items or page*500 >= total:
            break
        time.sleep(0.15)
    if len(result) < 1000:
        raise RuntimeError(f"Discovery returned only {len(result)} securities; refusing partial universe")
    return [result[k] for k in sorted(result)]

def history(symbol):
    param = f"{symbol},day,,,{COUNT},qfq"
    failures = []
    for host in HOSTS:
        url = host + "/appstock/app/fqkline/get?" + urlencode({"param":param})
        try:
            req = Request(url, headers={"User-Agent":"Mozilla/5.0", "Referer":"https://gu.qq.com/"})
            with urlopen(req, timeout=18) as resp:
                payload = json.load(resp)
            node = (payload.get("data") or {}).get(symbol) or {}
            bars = node.get("qfqday", node.get("day"))
            if not isinstance(bars, list) or not bars:
                raise ValueError("empty K-line")
            rows = []
            for b in bars:
                dt = str(b[0])
                datetime.strptime(dt, "%Y-%m-%d")
                o,c,h,l,v = map(float,b[1:6])
                if not (0 < l <= min(o,c) <= max(o,c) <= h and v >= 0):
                    raise ValueError("bad OHLCV")
                rows.append([symbol,dt,o,h,l,c,v])
            rows.sort(key=lambda r:r[1])
            if len({r[1] for r in rows}) != len(rows):
                raise ValueError("duplicate dates")
            if rows[-1][1] > datetime.now(timezone.utc).date().isoformat():
                raise ValueError("future bar")
            return rows, host
        except Exception as exc:
            failures.append(f"{host}: {type(exc).__name__} {exc}")
    raise RuntimeError("; ".join(failures))

def main():
    started = datetime.now(timezone.utc).isoformat()
    universe = discover()
    with (ROOT/"universe.csv").open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=["symbol","name"])
        writer.writeheader()
        writer.writerows(universe)
    selected = universe[:MAX_SYMBOLS]
    rows, errors, sources = [], {}, {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(history,stock["symbol"]):stock["symbol"] for stock in selected}
        for fut in as_completed(futures):
            sym=futures[fut]
            try:
                bars,host=fut.result()
                rows.extend(bars)
                sources[sym]=host
                print(f"OK {sym} {len(bars)}",flush=True)
            except Exception as exc:
                errors[sym]=str(exc)
                print(f"FAIL {sym}: {exc}",flush=True)
    rows.sort(key=lambda r:(r[0],r[1]))
    latest={}
    for row in rows:
        latest[row[0]]=row
    with gzip.open(ROOT/"history_120.csv.gz","wt",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["symbol","date","open","high","low","close","volume"])
        writer.writerows(rows)
    with (ROOT/"latest_snapshot.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.writer(f)
        writer.writerow(["symbol","date","open","high","low","close","volume"])
        writer.writerows(latest[s] for s in sorted(latest))
    report={"started_utc":started,"completed_utc":datetime.now(timezone.utc).isoformat(),
            "universe_count":len(universe),"requested_count":len(selected),
            "successful_count":len(sources),"failed_count":len(errors),
            "bar_count":len(rows),"coverage":"pilot_subset" if len(selected)<len(universe) else "full_requested",
            "errors":errors,"source_hosts":sources,
            "caveats":["Intraday last bar may be incomplete; only trust after close.",
                       "qfq adjusted prices; Tencent volume units differ for STAR Market.",
                       "No turnover amount or sector taxonomy included."]}
    (ROOT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("errors","source_hosts")},ensure_ascii=False),flush=True)
    if errors:
        raise SystemExit(f"{len(errors)} failed tickers; see report.json")
if __name__=="__main__":
    main()
