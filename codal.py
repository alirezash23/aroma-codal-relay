"""
codal.py — هسته واکشی اطلاعیه‌های کدال برای Aroma
=================================================
اینجا هیچ تحلیلی انجام نمی‌شود. وظیفه این ماژول فقط این است که
اطلاعیه‌ها را تمیز، تاریخ‌دار، لینک‌دار و با برچسب حقوق بازنشر
تحویل بدهد. تحلیل جای دیگری انجام می‌شود.

قواعدی که مستقیم از Master System Prompt v4.0 آمده‌اند:
- اولویت منبع: کدال، و تلگرام فقط مسیر موقت (نه منبع اصلی)
- هر آیتم برچسب rights دارد (نقل کامل آزاد / فقط مفهوم / بازنویسی اجباری)
- تیپ شرکت همراه آیتم می‌آید تا قانون حذف نویز قابل اعمال باشد
"""

import json
import os
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import jdatetime
import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------------
# تنظیمات
# ----------------------------------------------------------------------
SEARCH_URL = "https://search.codal.ir/api/search/v2/q"
MY_CODAL_URL = "https://my.codal.ir/"
CODAL_BASE = "https://codal.ir"
TELEGRAM_URL = "https://t.me/s/Codal360_ir"

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "6"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "900"))
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "1") == "1"
ENABLE_SEARCH_CODAL = os.getenv("ENABLE_SEARCH_CODAL", "0") == "1"

# لیارا (داخل ایران) به t.me وصل نمی‌شود — تلگرام در ایران فیلتر است،
# صرف‌نظر از این‌که سرور کجای دنیا میزبانی شده. اما گیت‌هاب فیلتر نیست
# و می‌تواند تلگرام را بخواند. پس: Actions هر روز تلگرام را می‌خواند و
# در خود مخزن ذخیره می‌کند (snapshot.py)، و این سرویس آن فایل ذخیره‌شده
# را از raw.githubusercontent.com می‌خواند — که از لیارا هم در دسترس است.
SNAPSHOT_RAW_URL = os.getenv(
    "SNAPSHOT_RAW_URL",
    "https://raw.githubusercontent.com/alirezash23/aroma-codal-relay/main/data/latest.json",
)
SNAPSHOT_CACHE_TTL = int(os.getenv("SNAPSHOT_CACHE_TTL", "300"))  # ۵ دقیقه
COMPANIES_PATH = os.getenv("COMPANIES_PATH", "companies.json")

CODAL_DEFAULT_PARAMS = {
    "Audited": "true", "AuditorRef": "-1", "Category": "-1", "Childs": "true",
    "CompanyState": "-1", "CompanyType": "-1", "Consolidatable": "true",
    "IsNotAudited": "false", "Length": "-1", "LetterType": "-1", "Mains": "true",
    "NotAudited": "true", "NotConsolidatable": "true", "Publisher": "false",
    "TracingNo": "-1", "search": "true",
}

# حقوق بازنشر — تفکیک حقوقی است، نه سلیقه‌ای (v4.0)
RIGHTS_FREE = "free_full"            # نقل کامل آزاد
RIGHTS_CONCEPT = "concept_only"      # فقط مفهوم و جهت، بدون رقم
RIGHTS_REWRITE = "rewrite_required"  # واقعیت رویداد آزاد، جمله‌بندی بازنویسی شود

SOURCE_RIGHTS = {
    "codal": RIGHTS_FREE,
    "tsetmc": RIGHTS_FREE,
    "company_ir": RIGHTS_FREE,
    "iea": RIGHTS_FREE, "eia": RIGHTS_FREE, "opec": RIGHTS_FREE, "gov": RIGHTS_FREE,
    "argus": RIGHTS_CONCEPT, "icis": RIGHTS_CONCEPT, "platts": RIGHTS_CONCEPT,
    "spglobal": RIGHTS_CONCEPT, "woodmac": RIGHTS_CONCEPT,
    "telegram": RIGHTS_REWRITE, "news": RIGHTS_REWRITE,
}

IMPORTANT_KEYWORDS = [
    "افشای اطلاعات بااهمیت", "افشا", "فعالیت ماهانه", "صورت‌های مالی",
    "صورتهای مالی", "تعدیل", "پیش‌بینی", "توقف", "تعلیق", "قرارداد",
    "نرخ خوراک", "افزایش سرمایه", "تقسیم سود", "مجمع", "تولید و فروش",
]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Referer": "https://codal.ir/",
})

_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()


# ----------------------------------------------------------------------
# ابزارها
# ----------------------------------------------------------------------
def normalize_fa(text: str) -> str:
    """یکسان‌سازی ی/ک عربی، نیم‌فاصله و فاصله اضافه."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = (text.replace("\u064a", "\u06cc").replace("\u0649", "\u06cc")
                .replace("\u0643", "\u06a9").replace("\u200c", " ")
                .replace("\u200f", "").replace("\u200e", ""))
    return re.sub(r"\s+", " ", text).strip()


def load_companies() -> Dict[str, Any]:
    try:
        with open(COMPANIES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        companies = data.get("companies", [])
        return {
            "list": companies,
            "by_symbol": {normalize_fa(c["symbol"]): c for c in companies},
            "type_rules": data.get("type_rules", {}),
        }
    except Exception as e:
        print(f"[COMPANIES] load failed: {e}")
        return {"list": [], "by_symbol": {}, "type_rules": {}}


COMPANIES = load_companies()


def symbols() -> List[str]:
    return [c["symbol"] for c in COMPANIES["list"]]


def company_of(symbol: str) -> Dict[str, Any]:
    return COMPANIES["by_symbol"].get(normalize_fa(symbol), {})


def jalali_today() -> jdatetime.date:
    return jdatetime.date.today()


def jalali_str(d: jdatetime.date) -> str:
    return d.strftime("%Y/%m/%d")


def parse_codal_datetime(value: str) -> Optional[datetime]:
    """کدال تاریخ را شمسی می‌دهد: '1404/05/26 08:11:53' → datetime میلادی."""
    if not value:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return jdatetime.datetime.strptime(value.strip(), fmt).togregorian()
        except Exception:
            continue
    return None


def cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        hit = _cache.get(key)
    if not hit or time.time() - hit["at"] > CACHE_TTL:
        return None
    return hit["data"]


def cache_set(key: str, data: Any) -> None:
    with _cache_lock:
        _cache[key] = {"at": time.time(), "data": data}


def cache_clear() -> None:
    with _cache_lock:
        _cache.clear()


# ----------------------------------------------------------------------
# منبع اصلی — search.codal.ir
# ----------------------------------------------------------------------
def fetch_codal(symbol: str, from_date: str, to_date: str,
                 timeout: Optional[int] = None, max_pages: int = 5) -> Dict[str, Any]:
    params = dict(CODAL_DEFAULT_PARAMS)
    params.update({"Symbol": symbol, "FromDate": from_date,
                   "ToDate": to_date, "PageNumber": "1"})
    items: List[Dict[str, Any]] = []
    target = normalize_fa(symbol)
    timeout = timeout or REQUEST_TIMEOUT
    try:
        for page in range(1, max_pages + 1):
            params["PageNumber"] = str(page)
            r = session.get(SEARCH_URL, params=params, timeout=timeout)
            if r.status_code != 200:
                return {"items": items, "error": f"http {r.status_code}"}
            data = r.json()
            letters = data.get("Letters") or []
            if not letters:
                break
            for letter in letters:
                # حتی اگر API پارامتر Symbol را نادیده بگیرد، اینجا فیلتر می‌کنیم
                if normalize_fa(letter.get("Symbol", "")) != target:
                    continue
                items.append(build_item(letter, symbol))
            if page >= int(data.get("Page") or 1):
                break
        return {"items": items, "error": None}
    except Exception as e:
        return {"items": items, "error": f"{type(e).__name__}: {e}"}


def build_item(letter: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    url = letter.get("Url") or letter.get("AttachmentUrl") or ""
    if url.startswith("/"):
        url = CODAL_BASE + url
    published_jalali = letter.get("PublishDateTime") or letter.get("SentDateTime") or ""
    dt = parse_codal_datetime(published_jalali)
    company = company_of(letter.get("Symbol") or symbol)
    return {
        "id": str(letter.get("TracingNo") or f"{symbol}-{abs(hash(letter.get('Title')))}"),
        "symbol": letter.get("Symbol") or symbol,
        "company": letter.get("CompanyName") or company.get("name", ""),
        "company_type": company.get("type", "unknown"),
        "title": normalize_fa(letter.get("Title") or ""),
        "letter_code": letter.get("LetterCode") or "",
        "period": letter.get("PeriodEndToDate") or "",
        "published_jalali": published_jalali,
        "published_iso": dt.isoformat() if dt else None,
        "url": url,
        "has_html": bool(letter.get("HasHtml")),
        "source": "codal",
        "rights": SOURCE_RIGHTS["codal"],
        "body": None,
        "body_status": "not_fetched",
    }


# ----------------------------------------------------------------------
# منبع my.codal.ir — SPA جاوااسکریپتی، بدون API مستند شناخته‌شده
# ----------------------------------------------------------------------
def probe_my_codal(symbol: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """
    my.codal.ir یک اپلیکیشن جاوااسکریپتی است — محتوای واقعی داخل مرورگر
    ساخته می‌شود، نه در HTML اولیه. این تابع صادقانه فقط تشخیص می‌دهد:
    اصلاً جواب می‌دهد؟ چقدر HTML برمی‌گردد؟ داخلش چیزی شبیه داده واقعی هست
    یا فقط پوسته خالی برنامه (یک <div id="app"></div> خالی)؟

    خروجی این تابع تصمیم می‌گیرد که آیا ارزش نوشتن یک اسکرِیپر واقعی
    برای این منبع هست یا نه — حدس زدن endpoint داخلی‌اش بدون مستندات
    وقت‌تلف‌کنی است.
    """
    try:
        r = session.get(MY_CODAL_URL, params={"symbol": symbol},
                        timeout=timeout or REQUEST_TIMEOUT)
        text = r.text or ""
        # نشانه‌های ساده یک SPA خالی: بدنه کوتاه، یا فقط یک div ریشه بدون محتوا
        looks_like_empty_shell = len(text) < 3000 and (
            'id="app"' in text or 'id="root"' in text or "ng-app" in text)
        return {
            "reachable": True,
            "status_code": r.status_code,
            "html_length": len(text),
            "looks_like_empty_shell": looks_like_empty_shell,
            "preview": normalize_fa(text[:600]),
            "error": None,
        }
    except Exception as e:
        return {"reachable": False, "status_code": None, "html_length": 0,
                "looks_like_empty_shell": None, "preview": "",
                "error": f"{type(e).__name__}: {e}"}


# ----------------------------------------------------------------------
# متن کامل اطلاعیه
# ----------------------------------------------------------------------
def fetch_body(item: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
    """
    قواعد راستی‌آزمایی v4.0 (اتحاد موجودی، قاعده مخرج، زنجیره تخصیص سود)
    روی متن خود سند کار می‌کنند، نه روی عنوان. این تابع بدنه اطلاعیه را می‌کشد.

    توجه: کدال ساختار صفحه اطلاعیه را گاهی عوض می‌کند. اگر body_status
    برابر 'empty' برگشت، سلکتورهای پایین باید با ساختار روز تطبیق داده شوند.
    """
    if not item.get("url"):
        item["body_status"] = "no_url"
        return item
    try:
        r = session.get(item["url"], timeout=timeout or REQUEST_TIMEOUT)
        if r.status_code != 200:
            item["body_status"] = f"http {r.status_code}"
            return item
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = normalize_fa(soup.get_text(" ", strip=True))
        tables = [
            [[normalize_fa(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
             for tr in tbl.find_all("tr")]
            for tbl in soup.find_all("table")
        ]
        item["body"] = text[:200000] or None
        item["tables"] = [t for t in tables if t]
        item["body_status"] = "ok" if text else "empty"
    except Exception as e:
        item["body_status"] = f"{type(e).__name__}: {e}"
    return item


# ----------------------------------------------------------------------
# مسیر موقت — تلگرام
# ----------------------------------------------------------------------
def fetch_telegram_posts() -> Dict[str, Any]:
    cached = cache_get("telegram_posts")
    if cached is not None:
        return cached
    result: Dict[str, Any] = {"posts": [], "error": None}
    try:
        r = session.get(TELEGRAM_URL, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            result["error"] = f"http {r.status_code}"
            return result
        soup = BeautifulSoup(r.text, "lxml")
        for block in soup.select("div.tgme_widget_message"):
            body = block.select_one("div.tgme_widget_message_text")
            if not body:
                continue
            t = block.select_one("time[datetime]")
            result["posts"].append({
                "text": normalize_fa(body.get_text(" ", strip=True)),
                "published_iso": t["datetime"] if t else None,
                "post": block.get("data-post"),
            })
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
    cache_set("telegram_posts", result)
    return result


def match_symbol(symbol: str, name: str, text: str) -> Optional[str]:
    """
    تطبیق نماد در متن آزاد تلگرام.

    این تابع عمداً سخت‌گیر است. تجربه اولین اجرای واقعی:
    جستجوی ساده نماد در متن، «خراسان» را داخل «#اخشان_خراسان» و
    «بوعلی» را داخل «#سرمایه_گذاری_بوعلی» مچ می‌کرد و اطلاعیه یک شرکت
    را به شرکت دیگری نسبت می‌داد. یک انتساب غلط از ده اطلاعیه ازدست‌رفته
    گران‌تر است، پس اینجا دقت بر پوشش مقدم است.

    دو مسیر پذیرفته‌شده:
    - هشتگ دقیق نماد: #زاگرس  (ولی نه #جم_پیلن برای نماد جم)
    - نام کامل شرکت در متن: «پتروشیمی جم»

    برای هشتگ، زیرخط دست‌نخورده می‌ماند تا #جم_پیلن با #جم اشتباه نشود.
    برای نام شرکت، زیرخط به فاصله تبدیل می‌شود تا #پتروشیمی_جم خوانده شود.
    """
    raw = normalize_fa(text)
    flat = re.sub(r"[_\-]+", " ", raw)
    if re.search(rf"#\s*{re.escape(normalize_fa(symbol))}(?![\w\u200c])", raw):
        return "hashtag"
    n = normalize_fa(name)
    if n and n in flat:
        return "company_name"
    return None


def match_telegram(symbol: str, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    company = company_of(symbol)
    out = []
    for p in posts:
        how = match_symbol(symbol, company.get("name", ""), p["text"])
        if not how:
            continue
        out.append({
            "matched_by": how,
            "id": p.get("post") or f"tg-{abs(hash(p['text']))}",
            "symbol": symbol,
            "company": company.get("name", ""),
            "company_type": company.get("type", "unknown"),
            "title": p["text"][:400],
            "letter_code": "", "period": "",
            "published_jalali": "", "published_iso": p.get("published_iso"),
            "url": f"https://t.me/{p['post']}" if p.get("post") else TELEGRAM_URL,
            "has_html": False,
            "source": "telegram",
            "rights": SOURCE_RIGHTS["telegram"],
            "body": None, "body_status": "not_applicable",
            "warning": "مسیر موقت. در متن به «اطلاعیه کدال» ارجاع بده نه به کانال. "
                       "هر عدد در اولین فرصت با خود سند تطبیق داده شود.",
        })
    return out


def load_remote_snapshot(timeout: int = 10) -> Dict[str, Any]:
    """
    فایل data/latest.json را از raw.githubusercontent.com می‌خواند —
    همان فایلی که GitHub Actions هر روز با snapshot.py می‌سازد.
    این مسیر چون از سرور ابری خارج از ایران (گیت‌هاب) پر می‌شود و
    raw.githubusercontent.com از داخل ایران هم در دسترس است، دور زدن
    مشکل «تلگرام در ایران فیلتر است، کدال IP ابری را می‌بندد» است.
    """
    cached = cache_get("remote_snapshot")
    if cached is not None:
        return cached
    try:
        r = session.get(SNAPSHOT_RAW_URL, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        data["_fetch_error"] = None
        cache_set("remote_snapshot", data)
        return data
    except Exception as e:
        return {"items": [], "errors": {}, "sources_used": [],
                "generated_at_jalali": None, "generated_at_iso": None,
                "_fetch_error": f"{type(e).__name__}: {e}"}


def serve_snapshot(days: Optional[int] = None,
                   only: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    داده را از اسنپ‌شات از‌پیش‌ذخیره‌شده گیت‌هاب سرو می‌کند — نه با
    درخواست زنده به تلگرام. برای استفاده در main.py وقتی سرویس روی
    زیرساختی اجرا می‌شود که به t.me دسترسی مستقیم ندارد (مثل لیارا).
    """
    snap = load_remote_snapshot()
    items = list(snap.get("items", []))

    if only:
        targets = {normalize_fa(s) for s in only}
        items = [i for i in items if normalize_fa(i.get("symbol", "")) in targets]

    if days:
        items = filter_by_days(items, days)

    errors = dict(snap.get("errors", {}))
    if snap.get("_fetch_error"):
        errors["snapshot_fetch"] = snap["_fetch_error"]

    return {
        "items": items,
        "errors": errors,
        "sources_used": snap.get("sources_used", []),
        "range": snap.get("range", {}),
        "snapshot_generated_at_jalali": snap.get("generated_at_jalali"),
        "snapshot_generated_at_iso": snap.get("generated_at_iso"),
    }


# ----------------------------------------------------------------------
# موتور — واکشی زنده (فقط از جایی کار می‌کند که هم به کدال هم به تلگرام
# دسترسی داشته باشد؛ از لیارا تلگرام فیلتر است. این تابع را snapshot.py
# روی گیت‌هاب صدا می‌زند، نه main.py مستقیم روی لیارا)
# ----------------------------------------------------------------------
def collect(days: int = 1, only: Optional[List[str]] = None,
            with_body: bool = False) -> Dict[str, Any]:
    targets = only or symbols()
    if not targets:
        return {"items": [], "errors": {"companies": "empty"},
                "sources_used": [], "range": {}}

    key = f"collect:{days}:{with_body}:{','.join(targets)}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    to_j = jalali_today()
    from_j = jdatetime.date.fromgregorian(
        date=to_j.togregorian() - timedelta(days=max(days - 1, 0)))
    from_date, to_date = jalali_str(from_j), jalali_str(to_j)

    items: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    missing: List[str] = list(targets)

    # search.codal.ir تأیید شده که از IP سرورهای ابری (گیت‌هاب و لیارا،
    # حتی build-در-ایران) قابل دسترسی نیست — ConnectTimeout در هر دو تست.
    # به‌جای تلف‌کردن ۲۰ ثانیه به‌ازای هر نماد، پیش‌فرض خاموش است.
    # اگر یک VPS/IP دیگر امتحان شد که وصل می‌شود، با
    # ENABLE_SEARCH_CODAL=1 دوباره روشنش کن.
    if ENABLE_SEARCH_CODAL:
        missing = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for symbol, res in pool.map(
                    lambda s: (s, fetch_codal(s, from_date, to_date)), targets):
                if res["error"]:
                    errors[symbol] = res["error"]
                if res["items"]:
                    items.extend(res["items"])
                else:
                    missing.append(symbol)

    sources_used = ["codal"] if items else []

    # my.codal.ir: هنوز API واقعی‌اش مستند نشده — probe_my_codal فقط
    # تشخیص می‌دهد جواب می‌دهد یا نه و چه چیزی برمی‌گرداند. تا وقتی
    # جواب واقعی‌اش را از /debug/mycodal ندیده‌ایم، اینجا آیتمی تولید
    # نمی‌کند — این صادقانه‌تر از حدس‌زدن یک ساختار ناموجود است.

    if TELEGRAM_ENABLED and missing:
        tg = fetch_telegram_posts()
        if tg["error"]:
            errors["telegram"] = tg["error"]
        else:
            for symbol in missing:
                found = match_telegram(symbol, tg["posts"])
                if found:
                    items.extend(found)
                    if "telegram" not in sources_used:
                        sources_used.append("telegram")

    items = filter_by_days(dedupe(items), days)
    items.sort(key=lambda i: i.get("published_iso") or "", reverse=True)

    if with_body:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            items = list(pool.map(
                lambda i: fetch_body(i) if i["source"] == "codal" else i, items))

    out = {"items": items, "errors": errors, "sources_used": sources_used,
           "range": {"from": from_date, "to": to_date}}
    cache_set(key, out)
    return out


def dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for i in items:
        k = i.get("id") or (i.get("symbol"), i.get("title"))
        if k in seen:
            continue
        seen.add(k)
        out.append(i)
    return out


def filter_by_days(items: List[Dict[str, Any]], days: int) -> List[Dict[str, Any]]:
    """آیتم بدون تاریخ حذف نمی‌شود تا چیزی خاموش گم نشود."""
    cutoff = datetime.now() - timedelta(days=days)
    out = []
    for i in items:
        iso = i.get("published_iso")
        if not iso:
            out.append(i)
            continue
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            out.append(i)
            continue
        if dt >= cutoff:
            out.append(i)
    return out


def is_important(item: Dict[str, Any]) -> bool:
    title = normalize_fa(item.get("title", ""))
    return any(normalize_fa(k) in title for k in IMPORTANT_KEYWORDS)
