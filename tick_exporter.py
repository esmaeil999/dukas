#!/usr/bin/env python3
"""Download Dukascopy tick data (the same public feed JForex uses) and export to CSV."""

import argparse
import lzma
import struct
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

def point_divisor(instrument: str) -> int:
    # JPY pairs have 3 decimals, the rest have 5
    return 1000 if "JPY" in instrument else 100000

def fmt_price(value: float, div: int) -> str:
    s = f"{value / div:.6f}".rstrip("0")
    return s[:-1] if s.endswith(".") else s

def fmt_volume(v: float) -> str:
    s = f"{v:.2f}".rstrip("0")
    return s[:-1] if s.endswith(".") else s

def decompress_bi5(raw: bytes) -> bytes:
    """bi5 files are LZMA without standard headers; try formats in order."""
    try:
        return lzma.decompress(raw)
    except lzma.LZMAError:
        return lzma.decompress(
            raw,
            format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA1, "preset": 9}],
        )

def fetch_hour(instrument: str, dt: datetime, retries: int = 3):
    """Fetch one hour of ticks. Returns list of (ms_offset, ask, bid, ask_vol, bid_vol)."""
    url = (
    f"https://datafeed.dukascopy.com/datafeed/{instrument}/"
    f"{dt.year:04d}/{dt.month - 1:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
            if not raw:
                return []
            data = decompress_bi5(raw)
            return list(struct.iter_unpack(">IIIff", data))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []  # weekend / holiday / no data
            if attempt == retries - 1:
                raise
        except Exception:
            if attempt == retries - 1:
                raise
        time.sleep(2 * (attempt + 1))
    return []

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--instrument", default="EURUSD")
    p.add_argument("--start", dest="from_", required=True, help='e.g. "2025-01-01 00:00:00" (GMT)')
    p.add_argument("--to", required=True, help='e.g. "2025-01-02 00:00:00" (GMT)')
    p.add_argument("--out", default="ticks.csv")
    args = p.parse_args()

    inst = args.instrument.upper()
    div = point_divisor(inst)
    start = datetime.strptime(args.from_, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.to, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    total = 0
    cursor = start
    with open(args.out, "w", buffering=1 << 20) as f:
        f.write("GmtTime,Bid,Ask,BidVolume,AskVolume\n")
        while cursor < end:
            ticks = fetch_hour(inst, cursor)
            for ms, ask, bid, ask_vol, bid_vol in ticks:
                ts = cursor + timedelta(milliseconds=ms)
                if ts < start or ts >= end:
                    continue
                line = (
                    f"{ts.strftime('%Y-%m-%d %H:%M:%S')}.{ts.microsecond // 1000:03d},"
                    f"{fmt_price(bid, div)},{fmt_price(ask, div)},"
                    f"{fmt_volume(bid_vol)},{fmt_volume(ask_vol)}\n"
                )
                f.write(line)
                total += 1
            print(f"hour: {cursor:%Y-%m-%d %H:%M} | ticks: {len(ticks)} | total: {total}", flush=True)
            cursor += timedelta(hours=1)
            time.sleep(0.15)  # be polite to the datafeed

    print(f"FINISHED. total ticks = {total}")

if __name__ == "__main__":
    sys.exit(main())
