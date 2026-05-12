#!/usr/bin/env python3
"""Headless browser diagnosis of /portal/facturas invoice list bug.

Launches Chromium, injects a signed session cookie, navigates to the
facturas page for two different months, and captures:
- All console messages (errors, warnings, logs)
- All network requests with status codes
- DOM state of #tableBody, #emptyState, #loadErrorState
- Screenshots
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

# Generate a signed session cookie
from services.auth.session import sign_session
from config import SESSION_COOKIE_NAME

USER_ID = 4
ISSUER_ID = 4
BASE_URL = "http://localhost:8000"

# Months to test: one "problem" month and one "working" month
TEST_MONTHS = [
    ("2026-05", "/tmp/facturas_2026-05.png"),
    ("2026-02", "/tmp/facturas_2026-02.png"),
]


def diagnose_page(page, url, screenshot_path, label):
    """Navigate to a URL and collect all diagnostic info."""
    console_msgs = []
    network_log = []

    def on_console(msg):
        console_msgs.append({
            "type": msg.type,
            "text": msg.text,
            "location": f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}",
        })

    def on_response(response):
        network_log.append({
            "url": response.url,
            "status": response.status,
            "ok": response.ok,
        })

    page.on("console", on_console)
    page.on("response", on_response)

    print(f"\n{'='*60}")
    print(f"  {label}: {url}")
    print(f"{'='*60}")

    page.goto(url, wait_until="networkidle", timeout=15000)
    # Extra wait for any delayed JS
    time.sleep(3)

    # Screenshot
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"  Screenshot: {screenshot_path}")

    # DOM inspection
    table_body = page.query_selector("#tableBody")
    empty_state = page.query_selector("#emptyState")
    load_error = page.query_selector("#loadErrorState")
    table_wrap = page.query_selector("#tableWrap")
    mobile_list = page.query_selector("#invoiceListMobile")

    print(f"\n  DOM State:")
    if table_body:
        rows = table_body.query_selector_all("tr")
        inner = table_body.inner_html()[:500]
        print(f"    #tableBody: {len(rows)} rows")
        print(f"    #tableBody innerHTML (first 500 chars): {inner}")
    else:
        print(f"    #tableBody: NOT FOUND")

    if table_wrap:
        display = table_wrap.evaluate("el => getComputedStyle(el).display")
        print(f"    #tableWrap display: {display}")
    else:
        print(f"    #tableWrap: NOT FOUND")

    if empty_state:
        display = empty_state.evaluate("el => getComputedStyle(el).display")
        visible = empty_state.is_visible()
        print(f"    #emptyState visible={visible}, display={display}")
    else:
        print(f"    #emptyState: NOT FOUND")

    if load_error:
        display = load_error.evaluate("el => getComputedStyle(el).display")
        visible = load_error.is_visible()
        inner = load_error.inner_text()[:200]
        print(f"    #loadErrorState visible={visible}, display={display}, text={inner}")
    else:
        print(f"    #loadErrorState: NOT FOUND")

    if mobile_list:
        cards = mobile_list.query_selector_all(".invoice-card, .mobile-card, [class*='card']")
        print(f"    #invoiceListMobile: {len(cards)} cards")
    else:
        print(f"    #invoiceListMobile: NOT FOUND")

    # Metric cards (totals)
    metric_cards = page.query_selector_all(".metric-card, .stat-card, [class*='metric']")
    print(f"    Metric/stat cards found: {len(metric_cards)}")

    # Check for skeleton loaders still visible
    skeletons = page.query_selector_all(".skeleton, [class*='skeleton'], .loading")
    visible_skeletons = [s for s in skeletons if s.is_visible()]
    print(f"    Skeleton loaders still visible: {len(visible_skeletons)}")

    # Console messages
    errors = [m for m in console_msgs if m["type"] in ("error", "warning")]
    print(f"\n  Console ({len(console_msgs)} total, {len(errors)} errors/warnings):")
    for m in console_msgs:
        prefix = "  !!" if m["type"] in ("error",) else "  W " if m["type"] == "warning" else "   "
        print(f"    {prefix} [{m['type']}] {m['text'][:200]}")
        if m["location"]:
            print(f"         at {m['location']}")

    # Network requests (only API calls and failures)
    api_calls = [n for n in network_log if "/api/" in n["url"]]
    failures = [n for n in network_log if not n["ok"]]
    print(f"\n  Network ({len(network_log)} total, {len(api_calls)} API, {len(failures)} failures):")
    for n in api_calls:
        status_mark = "OK" if n["ok"] else "FAIL"
        print(f"    [{status_mark} {n['status']}] {n['url'][:150]}")
    if failures:
        print(f"  Failed requests:")
        for n in failures:
            if "/api/" not in n["url"]:
                print(f"    [{n['status']}] {n['url'][:150]}")

    # Check if uiFetchJSON exists
    has_fetch = page.evaluate("typeof window.uiFetchJSON")
    print(f"\n  window.uiFetchJSON type: {has_fetch}")

    # Check page title and active tab
    title = page.title()
    print(f"  Page title: {title}")

    return {
        "label": label,
        "url": url,
        "console_errors": errors,
        "api_calls": api_calls,
        "network_failures": failures,
        "table_rows": len(table_body.query_selector_all("tr")) if table_body else 0,
        "empty_state_visible": empty_state.is_visible() if empty_state else "NOT FOUND",
        "skeletons_visible": len(visible_skeletons),
    }


def main():
    cookie_value = sign_session(user_id=USER_ID, issuer_id=ISSUER_ID)
    print(f"Session cookie: {SESSION_COOKIE_NAME}={cookie_value[:30]}...")

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        # Inject session cookie
        context.add_cookies([{
            "name": SESSION_COOKIE_NAME,
            "value": cookie_value,
            "domain": "localhost",
            "path": "/",
        }])

        page = context.new_page()

        for ym, screenshot_path in TEST_MONTHS:
            url = f"{BASE_URL}/portal/facturas?tab=issued&ym={ym}"
            result = diagnose_page(page, url, screenshot_path, f"Month {ym}")
            results.append(result)

        # Also test the API directly from the browser context
        print(f"\n{'='*60}")
        print(f"  Direct API test from browser")
        print(f"{'='*60}")
        for ym, _ in TEST_MONTHS:
            api_url = f"{BASE_URL}/api/invoices/issued?ym={ym}&page=1&per_page=50"
            response = page.evaluate(f"""
                async () => {{
                    try {{
                        const r = await fetch('{api_url}');
                        const data = await r.json();
                        return {{ status: r.status, ok: r.ok, data_keys: Object.keys(data),
                                  data_count: Array.isArray(data.data) ? data.data.length : 'not array',
                                  raw: JSON.stringify(data).substring(0, 500) }};
                    }} catch(e) {{
                        return {{ error: e.message }};
                    }}
                }}
            """)
            print(f"\n  API {ym}: {json.dumps(response, indent=2)}")

        browser.close()

    # Summary
    print(f"\n{'='*60}")
    print(f"  DIAGNOSIS SUMMARY")
    print(f"{'='*60}")
    for r in results:
        print(f"\n  {r['label']}:")
        print(f"    Table rows: {r['table_rows']}")
        print(f"    Empty state visible: {r['empty_state_visible']}")
        print(f"    Skeletons visible: {r['skeletons_visible']}")
        print(f"    Console errors: {len(r['console_errors'])}")
        print(f"    API calls: {len(r['api_calls'])}")
        print(f"    Network failures: {len(r['network_failures'])}")


if __name__ == "__main__":
    main()
