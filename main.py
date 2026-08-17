"""
main.py — Aroma Codal Relay API
"""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import jdatetime
from fastapi import FastAPI, Header, HTTPException, Query

import codal

API_KEY = os.getenv("API_KEY", "")

app = FastAPI(
    title="Aroma Codal Relay",
    version="4.0",
    description="اطلاعیه‌های کدال برای موتور تحلیل آروما. تحلیل اینجا انجام نمی‌شود.",
)


def check_auth(header_key: Optional[str], query_key: Optional[str] = None) -> None:
    """
    کلید یا در هدر X-API-Key می‌آید یا در پارامتر ?key=
    پارامتر برای تست ساده در مرورگر است؛ در اتصال ماشینی هدر را استفاده کن،
    چون query در لاگ سرور و تاریخچه مرورگر ثبت می‌شود.
    """
    if API_KEY and header_key != API_KEY and query_key != API_KEY:
        raise HTTPException(status_code=401,
                            detail="invalid or missing API key (X-API-Key header or ?key=)")


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "Aroma Codal Relay",
        "version": "4.0",
        "companies": len(codal.symbols()),
        "telegram_enabled": codal.TELEGRAM_ENABLED,
        "search_codal_enabled": codal.ENABLE_SEARCH_CODAL,
        "cache_ttl": codal.CACHE_TTL,
        "auth_required": bool(API_KEY),
        "time_jalali": codal.jalali_str(codal.jalali_today()),
        "time_iso": datetime.now().isoformat(),
    }


@app.get("/v1/companies")
def companies():
    return {"ok": True, "count": len(codal.COMPANIES["list"]),
            "companies": codal.COMPANIES["list"],
            "type_rules": codal.COMPANIES["type_rules"]}


@app.get("/v1/today")
def today(with_body: bool = False, key: Optional[str] = None,
          x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    check_auth(x_api_key, key)
    data = codal.collect(days=1, with_body=with_body)
    return {"ok": True, "date": codal.jalali_str(codal.jalali_today()),
            "count": len(data["items"]), **data}


@app.get("/v1/latest")
def latest(days: int = Query(30, ge=1, le=365), with_body: bool = False,
           key: Optional[str] = None,
           x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    check_auth(x_api_key, key)
    data = codal.collect(days=days, with_body=with_body)
    return {"ok": True, "days": days, "count": len(data["items"]), **data}


@app.get("/v1/important")
def important(days: int = Query(7, ge=1, le=365), with_body: bool = False,
              key: Optional[str] = None,
              x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    check_auth(x_api_key, key)
    data = codal.collect(days=days, with_body=with_body)
    picked = [i for i in data["items"] if codal.is_important(i)]
    return {"ok": True, "days": days, "count": len(picked), "items": picked,
            "errors": data["errors"], "sources_used": data["sources_used"],
            "range": data["range"]}


@app.get("/v1/symbol/{symbol}")
def by_symbol(symbol: str, days: int = Query(30, ge=1, le=365),
              with_body: bool = False, key: Optional[str] = None,
              x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    check_auth(x_api_key, key)
    data = codal.collect(days=days, only=[symbol], with_body=with_body)
    company = codal.company_of(symbol)
    rules = codal.COMPANIES["type_rules"].get(company.get("type", ""), {})
    return {"ok": True, "symbol": symbol, "days": days,
            "company": company, "type_rules": rules,
            "count": len(data["items"]), **data}


@app.post("/v1/reload")
def reload_companies(key: Optional[str] = None,
                     x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    check_auth(x_api_key, key)
    codal.COMPANIES = codal.load_companies()
    codal.cache_clear()
    return {"ok": True, "count": len(codal.symbols())}


@app.get("/debug/ping")
def debug_ping(target: str = "search"):
    """
    فقط دسترسی خام را با timeout کوتاه چک می‌کند — بدون منطق برنامه.
    target: search (پیش‌فرض، search.codal.ir) یا mycodal (my.codal.ir)
    جواب باید در کمتر از ۱۰ ثانیه بیاید.
    """
    import time as _time
    started = _time.time()

    if target == "mycodal":
        res = codal.probe_my_codal("فارس", timeout=8)
        res["elapsed_seconds"] = round(_time.time() - started, 2)
        res["ok"] = res["reachable"]
        return res

    to_j = codal.jalali_today()
    try:
        r = codal.session.get(
            codal.SEARCH_URL,
            params={**codal.CODAL_DEFAULT_PARAMS, "Symbol": "فارس",
                   "FromDate": codal.jalali_str(to_j), "ToDate": codal.jalali_str(to_j),
                   "PageNumber": "1"},
            timeout=8,
        )
        return {"ok": True, "reachable": True, "status_code": r.status_code,
                "elapsed_seconds": round(_time.time() - started, 2)}
    except Exception as e:
        return {"ok": False, "reachable": False,
                "error": f"{type(e).__name__}: {e}",
                "elapsed_seconds": round(_time.time() - started, 2)}


@app.get("/debug/mycodal")
def debug_mycodal(symbol: str = "فارس"):
    """
    خروجی کامل probe_my_codal — طول HTML و ۶۰۰ کاراکتر اول را نشان می‌دهد
    تا معلوم شود my.codal.ir واقعاً چه چیزی برمی‌گرداند. این خروجی را
    بفرست تا بشود فهمید ارزش نوشتن اسکرِیپر واقعی برایش هست یا نه.
    """
    return codal.probe_my_codal(symbol, timeout=10)


@app.get("/debug")
def debug(symbol: Optional[str] = None, with_body: bool = False):
    """
    خروجی این را بفرست تا معلوم شود کدام منبع جواب می‌دهد.
    هر درخواست حداکثر ۸ ثانیه صبر می‌کند و نمادها موازی واکشی می‌شوند،
    پس کل درخواست باید زیر ۱۵-۲۰ ثانیه تمام شود. اگر باز هم طولانی شد،
    اول /debug/ping را امتحان کن — سریع‌تر و تشخیصی‌تر است.
    """
    targets = [symbol] if symbol else codal.symbols()[:3]
    to_j = codal.jalali_today()
    from_j = jdatetime.date.fromgregorian(
        date=to_j.togregorian() - timedelta(days=7))
    from_date, to_date = codal.jalali_str(from_j), codal.jalali_str(to_j)
    out: Dict[str, Any] = {"range": {"from": from_date, "to": to_date}, "symbols": {}}

    with ThreadPoolExecutor(max_workers=max(len(targets), 1) + 1) as pool:
        codal_futures = {
            pool.submit(codal.fetch_codal, s, from_date, to_date, 8): s
            for s in targets
        }
        tg_future = pool.submit(codal.fetch_telegram_posts)

        results = {}
        for fut in codal_futures:
            s = codal_futures[fut]
            results[s] = fut.result()
        tg = tg_future.result()

    for s in targets:
        res = results[s]
        sample = res["items"][:1]
        if sample and with_body:
            sample = [codal.fetch_body(dict(sample[0]), timeout=8)]
            for it in sample:
                if it.get("body"):
                    it["body"] = it["body"][:600] + " …"
                it.pop("tables", None)
        out["symbols"][s] = {
            "codal_count": len(res["items"]),
            "codal_error": res["error"],
            "codal_sample": sample,
        }

    out["telegram"] = {"posts_fetched": len(tg["posts"]), "error": tg["error"],
                       "sample": tg["posts"][:2]}
    return out
