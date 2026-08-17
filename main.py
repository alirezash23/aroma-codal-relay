"""
main.py — Aroma Codal Relay API
"""

import os
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


@app.get("/debug")
def debug(symbol: Optional[str] = None):
    """خروجی این را بفرست تا معلوم شود کدام منبع جواب می‌دهد."""
    targets = [symbol] if symbol else codal.symbols()[:3]
    to_j = codal.jalali_today()
    from_j = jdatetime.date.fromgregorian(
        date=to_j.togregorian() - timedelta(days=7))
    out: Dict[str, Any] = {
        "range": {"from": codal.jalali_str(from_j), "to": codal.jalali_str(to_j)},
        "symbols": {},
    }
    for s in targets:
        res = codal.fetch_codal(s, codal.jalali_str(from_j), codal.jalali_str(to_j))
        sample = res["items"][:1]
        if sample:
            sample = [codal.fetch_body(dict(sample[0]))]
            for it in sample:
                if it.get("body"):
                    it["body"] = it["body"][:600] + " …"
                it.pop("tables", None)
        out["symbols"][s] = {
            "codal_count": len(res["items"]),
            "codal_error": res["error"],
            "codal_sample": sample,
        }
    tg = codal.fetch_telegram_posts()
    out["telegram"] = {"posts_fetched": len(tg["posts"]), "error": tg["error"],
                       "sample": tg["posts"][:2]}
    return out
