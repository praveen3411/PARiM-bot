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
    await page.goto(PARIM_URL + "/login", wait_until="networkidle", timeout=40000)
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

    await page.wait_for_load_state("networkidle", timeout=30000)
    await page.wait_for_timeout(3000)
    log(f"Logged in! URL={page.url}")

async def try_apply_on_page(target_page, page, applied):
    """Try to find and click Apply buttons on given page/frame"""
    btns = await target_page.query_selector_all('button:has-text("Apply")')
    log(f"  Apply buttons found: {len(btns)}")
    if not btns:
        return 0

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
                log(f"  Shift {i+1} already applied")
                continue

            log(f"  Clicking Apply for shift {i+1}: {text[:60]}")
            await btn.scroll_into_view_if_needed()
            await btn.click()
            await asyncio.sleep(3)
            await page.screenshot(path=f"screenshot_modal_{i}.png")

            confirmed = False
            for sel in [
                '.modal-footer .btn-success',
                '.modal-footer button:last-child',
                '.modal .btn-success',
                '.modal button:has-text("Apply")',
                '[role="dialog"] button:has-text("Apply")',
                'button.btn-success',
            ]:
                try:
                    mb = await target_page.query_selector(sel)
                    if mb and await mb.is_visible():
                        log(f"  Confirming via {sel}")
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
                log(f"  SUCCESS! Applied for shift {i+1}")
                await page.screenshot(path=f"screenshot_success_{i}.png")
            else:
                log(f"  No confirm button found")
        except Exception as e:
            log(f"  Error on shift {i+1}: {e}")
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
            # Step 1: Login
            await login(page)

            # Step 2: Load /staff to establish monolith session
            log("Loading /staff to establish session...")
            await page.goto(PARIM_URL + "/staff", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(6000)
            log(f"Frames: {[f.url for f in page.frames]}")
            await page.screenshot(path="screenshot_01_staff.png")

            total_applied = 0

            # METHOD A: Try navigating whole page directly to monolith event URL
            log("--- METHOD A: Direct page navigation to /s/event/ ---")
            for url_try in [PARIM_URL + "/s/event/", PARIM_URL + "/s/event/index"]:
                try:
                    log(f"  Trying {url_try}")
                    await page.goto(url_try, wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(4000)
                    log(f"  URL after goto: {page.url}")
                    await page.screenshot(path="screenshot_02_method_a.png")
                    content = await page.content()
                    log(f"  Has Apply: {'Apply' in content}, Has Open Shifts: {'Open Shifts' in content}")
                    if "Apply" in content or "Open Shifts" in content:
                        n = await try_apply_on_page(page, page, applied)
                        total_applied += n
                        if n > 0:
                            break
                except Exception as e:
                    log(f"  Method A failed: {e}")

            # METHOD B: Use frame.goto() on the monolith frame
            if total_applied == 0:
                log("--- METHOD B: frame.goto() on monolith frame ---")
                try:
                    # Re-load staff page first
                    await page.goto(PARIM_URL + "/staff", wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(5000)
                    log(f"  Frames: {[f.url for f in page.frames]}")

                    # Find monolith frame
                    mf = None
                    for f in page.frames:
                        if "/s/" in f.url:
                            mf = f
                            break
                    if not mf and len(page.frames) > 1:
                        mf = page.frames[1]
                    
                    if mf:
                        log(f"  Frame found: {mf.url}")
                        log(f"  Navigating frame to /s/event/index")
                        await mf.goto(PARIM_URL + "/s/event/index", wait_until="domcontentloaded", timeout=20000)
                        await asyncio.sleep(5)
                        log(f"  Frame URL after goto: {mf.url}")
                        await page.screenshot(path="screenshot_03_method_b.png")
                        content = await mf.content()
                        log(f"  Frame has Apply: {'Apply' in content}")
                        n = await try_apply_on_page(mf, page, applied)
                        total_applied += n
                    else:
                        log("  No frame found")
                except Exception as e:
                    log(f"  Method B error: {e}")
                    import traceback
                    log(traceback.format_exc())

            # METHOD C: contentDocument JavaScript
            if total_applied == 0:
                log("--- METHOD C: contentDocument JavaScript ---")
                try:
                    await page.goto(PARIM_URL + "/staff", wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(3000)
                    await page.evaluate(f"document.getElementById('monolith-iframe').src = '{PARIM_URL}/s/event/index'")
                    await asyncio.sleep(10)
                    await page.screenshot(path="screenshot_04_method_c.png")

                    result = await page.evaluate("""
                        () => {
                            try {
                                const iframe = document.getElementById('monolith-iframe');
                                const doc = iframe.contentDocument || iframe.contentWindow.document;
                                const btns = doc.querySelectorAll('button');
                                return {
                                    count: btns.length,
                                    applyCount: Array.from(btns).filter(b => b.textContent.trim() === 'Apply').length,
                                    bodyText: doc.body.innerText.substring(0, 200)
                                };
                            } catch(e) {
                                return {error: e.message};
                            }
                        }
                    """)
                    log(f"  contentDocument result: {result}")

                    apply_count = result.get('applyCount', 0) if isinstance(result, dict) else 0
                    for i in range(apply_count):
                        clicked = await page.evaluate(f"""
                            () => {{
                                const iframe = document.getElementById('monolith-iframe');
                                const doc = iframe.contentDocument || iframe.contentWindow.document;
                                const btns = Array.from(doc.querySelectorAll('button')).filter(b => b.textContent.trim() === 'Apply' && b.offsetParent);
                                if (btns[0]) {{ btns[0].click(); return 'clicked'; }}
                                return 'not found';
                            }}
                        """)
                        log(f"  Click result: {clicked}")
                        if clicked == 'clicked':
                            await asyncio.sleep(3)
                            confirmed = await page.evaluate("""
                                () => {
                                    const iframe = document.getElementById('monolith-iframe');
                                    const doc = iframe.contentDocument || iframe.contentWindow.document;
                                    const modal = doc.querySelector('.modal-footer .btn-success, .modal .btn-success');
                                    if (modal && modal.offsetParent) { modal.click(); return 'confirmed'; }
                                    const allBtns = Array.from(doc.querySelectorAll('button')).filter(b => b.textContent.trim() === 'Apply' && b.offsetParent);
                                    if (allBtns[0]) { allBtns[0].click(); return 'confirmed via btn'; }
                                    return 'not found';
                                }
                            """)
                            log(f"  Confirm result: {confirmed}")
                            if 'confirmed' in str(confirmed):
                                total_applied += 1
                                log(f"  SUCCESS via Method C!")
                                await page.screenshot(path=f"screenshot_success_c_{i}.png")
                            await asyncio.sleep(2)

                except Exception as e:
                    log(f"  Method C error: {e}")

            log(f"=== Total applied: {total_applied} ===")

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
