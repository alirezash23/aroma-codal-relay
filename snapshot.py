"""
snapshot.py — اجرای مستقل، بدون سرور.

روزی یک بار (با GitHub Actions یا cron) اجرا می‌شود، اطلاعیه‌های بازه
مشخص را می‌گیرد و در پوشه data/ می‌نویسد. اگر لیارا قطع بود، این مسیر
مستقل کار می‌کند و تاریخچه هم داخل خود مخزن باقی می‌ماند.

    python snapshot.py --days 1
    python snapshot.py --days 7 --with-body
"""

import argparse
import json
import os
import sys
from datetime import datetime

import codal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--with-body", action="store_true",
                    help="متن کامل اطلاعیه‌ها هم کشیده شود (کندتر)")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()

    data = codal.collect(days=args.days, with_body=args.with_body)
    today = codal.jalali_str(codal.jalali_today())

    payload = {
        "generated_at_jalali": today,
        "generated_at_iso": datetime.now().isoformat(),
        "days": args.days,
        "count": len(data["items"]),
        "sources_used": data["sources_used"],
        "errors": data["errors"],
        "range": data["range"],
        "items": data["items"],
    }

    os.makedirs(args.out, exist_ok=True)
    dated = os.path.join(args.out, f"{today.replace('/', '-')}.json")
    for path in (os.path.join(args.out, "latest.json"), dated):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"items={payload['count']} sources={payload['sources_used']} "
          f"errors={len(payload['errors'])}")

    # تلگرام حالا منبع اصلی و دائمی است — نه fallback موقت.
    # هم my.codal.ir و هم search.codal.ir تست شدند و از سرور لیارا
    # (build در ایران) هم ConnectTimeout گرفتند؛ کدال ظاهراً کل رنج
    # IP سرورهای ابری را می‌بندد، نه فقط بر اساس کشور. تصمیم آگاهانه:
    # تا اطلاع ثانوی، تلگرام تنها منبع است.
    if "telegram" not in payload["sources_used"]:
        print("TELEGRAM UNREACHABLE — no source responded", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
