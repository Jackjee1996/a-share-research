# A-share Research

Daily historical OHLCV research for 3–15 trading day swing trading. No real-time market feed or paid key required.

## Initial smoke test

The workflow fetches up to 120 daily bars for 10 A-share symbols via public Tencent historical K-line endpoints. It validates the payload and calculates MA5/MA10/MA20, writing CSV files to `data/`. This is an experimental public data source: availability is not guaranteed.

Use **Actions → A-share historical data smoke test → Run workflow** to run it manually. Scheduled runs occur at 19:30 Asia/Shanghai on weekdays (11:30 UTC); scheduled workflows may be delayed. The workflow commits CSV outputs on success and uploads artifacts for inspection. No financial advice or live trading orders.

Source inspiration: https://github.com/simonlin1212/a-stock-data
