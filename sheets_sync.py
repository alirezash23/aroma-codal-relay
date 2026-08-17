"""
sheets_sync.py — نوشتن اطلاعیه‌های data/latest.json در یک گوگل‌شیت.

پیش‌نیاز (یک‌بار، در گیت‌هاب Secrets):
    GOOGLE_SHEETS_CREDENTIALS  — کل محتوای فایل JSON حساب سرویس گوگل
    GOOGLE_SHEET_ID            — شناسه شیت (از آدرس شیت، بین /d/ و /edit)

اجرا:
    python sheets_sync.py

رفتار:
    - هر ردیف با id یکتای خودش نوشته می‌شود.
    - قبل از نوشتن، ستون ID موجود در شیت خوانده می‌شود تا آیتم تکراری
      دوباره اضافه نشود (idempotent — اجرای چندباره مشکلی نمی‌سازد).
    - اگر شیت خالی است، ابتدا هدر ستون‌ها نوشته می‌شود.
"""

import json
import os
import sys

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
WORKSHEET_NAME = os.getenv("GOOGLE_SHEET_TAB", "اطلاعیه‌ها")

HEADERS = [
    "تاریخ شمسی", "نماد", "شرکت", "نوع شرکت", "عنوان",
    "منبع", "نوع تطبیق", "حقوق بازنشر", "لینک", "ID",
]


def row_from_item(item: dict) -> list:
    return [
        item.get("published_jalali") or item.get("published_iso", "")[:10],
        item.get("symbol", ""),
        item.get("company", ""),
        item.get("company_type", ""),
        item.get("title", ""),
        item.get("source", ""),
        item.get("matched_by", ""),
        item.get("rights", ""),
        item.get("url", ""),
        item.get("id", ""),
    ]


def main() -> int:
    if not SHEET_ID or not CREDENTIALS_JSON:
        print("GOOGLE_SHEET_ID یا GOOGLE_SHEETS_CREDENTIALS ست نشده — رد شد", file=sys.stderr)
        return 1

    try:
        creds_dict = json.loads(CREDENTIALS_JSON)
    except json.JSONDecodeError as e:
        print(f"GOOGLE_SHEETS_CREDENTIALS معتبر نیست: {e}", file=sys.stderr)
        return 1

    with open("data/latest.json", "r", encoding="utf-8") as f:
        snapshot = json.load(f)
    items = snapshot.get("items", [])

    if not items:
        print("آیتمی در data/latest.json نیست — چیزی برای نوشتن وجود ندارد")
        return 0

    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh = client.open_by_key(SHEET_ID)

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=len(HEADERS))
        ws.append_row(HEADERS)

    # اگر شیت از اجرای قبلی با تعداد ستون کمتر ساخته شده (مثلاً قبل از
    # اضافه‌شدن ستون «نوع تطبیق»)، اول گسترشش بده وگرنه خواندن/نوشتن
    # ستون‌های جدید با خطای «Range exceeds grid limits» شکست می‌خورد.
    if ws.col_count < len(HEADERS):
        ws.resize(cols=len(HEADERS))

    header_row = ws.row_values(1)
    if header_row != HEADERS:
        ws.update("A1", [HEADERS])

    existing = ws.col_values(HEADERS.index("ID") + 1)
    existing_ids = set(existing[1:])  # ردیف اول هدر است

    new_rows = [row_from_item(i) for i in items if i.get("id") not in existing_ids]

    if not new_rows:
        print(f"{len(items)} آیتم بررسی شد، همه از قبل در شیت بودند")
        return 0

    ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    print(f"{len(new_rows)} ردیف جدید نوشته شد (از {len(items)} آیتم)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
