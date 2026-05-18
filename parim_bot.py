import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EMAIL = os.environ.get("PARIM_EMAIL", "")
PASSWORD = os.environ.get("PARIM_PASSWORD", "")
PARIM_URL = os.environ.get("PARIM_URL", "https://swordsecurityhq.parim.co")
APPLIED_FILE = Path("applied_shifts.json")

def log(msg):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)

def load_applied():
    if APPLIED_FILE.exists():
        try:
            return set(json.loads(APPLIED_FILE.read_text()))
        except Exception:
            pass
    return set()

def save_applied(applied):
    APPLIED_FILE.write_text(json.dumps(sorted(applied)))

async def login(page):
    log("Logging in...")
    await page.goto(PARIM_URL + "/login", wait_until="load", timeout=40000)
    await page.wait_for_timeout(3000)

    email_input = await page.wait_for_selector(
        'input[type="email"], input[name="email"], input[name="username"]', timeout=15000
    )
    await email_input.fill(EMAIL)

    next_btn = await page.query_selector('button:has-text("Next"), button:has-text("Continue")')
    if next_btn:
        await next_btn.click()
        await page.wait_for_timeout(3000)
        try:
            item = await page.wait_for_selector('li, .team-item', timeout=5000)
            if item:
                await item.click()
                await page.wait_for_timeout(3000)
        except Exception:
            pass

    pw_input = None
    for sel in ['input[type="password"]', 'input[name="password"]']:
        try:
            pw_input = await page.wait_for_selector(sel, timeout=8000)
            if pw_input:
                break
        except Exception:
            continue
    if not pw_input:
        raise Exception("Password field not found")

    await pw_input.fill(PASSWORD)
    btn = await page.query_selector('button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")')
    if btn:
        await btn.click()
    else:
        await pw_input.press("Enter")

    # Wait for redirect to /staff - use load not networkidle
    await page.wait_for_load_state("load", timeout=30000)
    await page.wait_for_timeout(5000)
    log(f"Logged in! URL={page.url}")

async def ensure_on_staff(page):
    """Make sure we are on the /staff page. Already there after login — just wait."""
    if "/staff" not in page.url:
        log(f"Not on /staff (on {page.url}), navigating...")
        await page.goto(PARIM_URL + "/staff", wait_until="load", timeout=30000)
        await page.wait_for_timeout(5000)
    else:
        log("Already on /staff - waiting for iframe to render...")
        await page.wait_for_timeout(6000)

    log(f"Staff page ready. Frames: {[f.url for f in page.frames]}")
    await page.screenshot(path="screenshot_01_staff.png")

async def try_apply(target, page, applied):
    btns = await target.query_selector_all('button:has-text("Apply")')
    log(f"Apply buttons: {len(btns)}")
    count = 0
    for i, btn in enumerate(btns):
        try:
            if not await btn.is_visible():
                continue
            try:
                row = await btn.evaluate_handle(
                    "el => el.closest('tr') || el.closest('[class*=row]') || el.parentElement?.parentElement"
                )
                text = (await row.inner_text()).strip()[:200]
            except Exception:
                text = f"shift_{i}"

            if text in applied:
                log(f"Already applied shift {i+1}")
                continue

            log(f"Applying shift {i+1}: {text[:60]}")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await asyncio.sleep(3)
            await page.screenshot(path=f"screenshot_modal_{i}.png")

            confirmed = False
            for sel in ['.modal-footer .btn-success', '.modal-footer button:last-child',
                        '.modal .btn-success', '.modal button:has-text("Apply")',
                        '[role="dialog"] button:has-text("Apply")', 'button.btn-success']:
                try:
                    mb = await target.query_selector(sel)
                    if mb and await mb.is_visible():
                        log(f"Confirming via {sel}")
                        await mb.click()
                        await asyncio.sleep(3)
                        confirmed = True
                        break
                except Exception:
                    continue

            if confirmed:
                applied.add(text)
                save_applied(applied)
                count += 1
                log(f"SUCCESS! Applied shift {i+1}")
                await page.screenshot(path=f"screenshot_done_{i}.png")
            else:
                log(f"No confirm button found for shift {i+1}")
        except Exception as e:
            log(f"Error shift {i+1}: {e}")
    return count

async def main():
    if not EMAIL or not PASSWORD:
        log("Secrets not set!")
        sys.exit(1)

    log("=== PARiM Bot Starting ===")
    applied = load_applied()
    log(f"History: {len(applied)} shifts")

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = await (await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )).new_page()

        try:
            await login(page)
            await ensure_on_staff(page)

            total = 0

            # METHOD A: frame.goto() on monolith frame
            log("--- METHOD A: frame.goto ---")
            try:
                mf = None
                for f in page.frames:
                    if "/s/" in f.url:
                        mf = f
                        break
                if not mf and len(page.frames) > 1:
                    mf = page.frames[1]

                log(f"Frame: {mf.url if mf else 'not found'}")
                if mf:
                    await mf.goto(PARIM_URL + "/s/event/index", wait_until="load", timeout=20000)
                    await asyncio.sleep(5)
                    log(f"Frame URL after goto: {mf.url}")
                    await page.screenshot(path="screenshot_02_frame.png")
                    content = await mf.content()
                    log(f"Frame has Apply: {'Apply' in content}, Open Shifts: {'Open Shifts' in content}")
                    n = await try_apply(mf, page, applied)
                    total += n
            except Exception as e:
                log(f"Method A error: {e}")

            # METHOD B: contentDocument if A found nothing
            if total == 0:
                log("--- METHOD B: contentDocument ---")
                try:
                    # Navigate iframe via JS
                    await page.evaluate(
                        f"document.getElementById('monolith-iframe').src = '{PARIM_URL}/s/event/index'"
                    )
                    await asyncio.sleep(10)
                    await page.screenshot(path="screenshot_03_contentdoc.png")

                    info = await page.evaluate("""
                        () => {
                            try {
                                const doc = document.getElementById('monolith-iframe').contentDocument
                                            || document.getElementById('monolith-iframe').contentWindow.document;
                                const applyBtns = Array.from(doc.querySelectorAll('button'))
                                    .filter(b => b.textContent.trim() === 'Apply' && b.offsetParent);
                                return {count: applyBtns.length, text: doc.body.innerText.substring(0,100)};
                            } catch(e) { return {error: e.message}; }
                        }
                    """)
                    log(f"contentDocument: {info}")

                    apply_count = info.get('count', 0) if isinstance(info, dict) else 0
                    for i in range(apply_count):
                        r = await page.evaluate("""
                            () => {
                                const doc = document.getElementById('monolith-iframe').contentDocument
                                            || document.getElementById('monolith-iframe').contentWindow.document;
                                const btn = Array.from(doc.querySelectorAll('button'))
                                    .find(b => b.textContent.trim() === 'Apply' && b.offsetParent);
                                if (btn) { btn.click(); return 'clicked'; }
                                return 'not found';
                            }
                        """)
                        log(f"Click: {r}")
                        if r == 'clicked':
                            await asyncio.sleep(3)
                            c = await page.evaluate("""
                                () => {
                                    const doc = document.getElementById('monolith-iframe').contentDocument
                                                || document.getElementById('monolith-iframe').contentWindow.document;
                                    const mb = doc.querySelector('.modal-footer .btn-success, .modal .btn-success');
                                    if (mb && mb.offsetParent) { mb.click(); return 'confirmed'; }
                                    return 'not found';
                                }
                            """)
                            log(f"Confirm: {c}")
                            if 'confirmed' in str(c):
                                total += 1
                                log(f"SUCCESS via Method B!")
                                await page.screenshot(path=f"screenshot_done_b_{i}.png")
                            await asyncio.sleep(3)
                except Exception as e:
                    log(f"Method B error: {e}")

            log(f"=== Done. Applied for {total} shift(s) ===")

        except Exception as e:
            log(f"=== FATAL: {e} ===")
            import traceback
            log(traceback.format_exc())
            try:
                await page.screenshot(path="screenshot_error.png")
            except Exception:
                pass
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
