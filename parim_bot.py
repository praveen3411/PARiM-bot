import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

EMAIL = os.environ.get(“PARIM_EMAIL”, “”)
PASSWORD = os.environ.get(“PARIM_PASSWORD”, “”)
PARIM_URL = os.environ.get(“PARIM_URL”, “https://swordsecurityhq.parim.co”)
APPLIED_FILE = Path(“applied_shifts.json”)

def log(msg, icon=“INFO”):
ts = datetime.utcnow().strftime(”%H:%M:%S UTC”)
print(f”[{ts}] {icon} {msg}”, flush=True)

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
login_url = PARIM_URL.rstrip(”/”) + “/login”
log(f”Opening {login_url}”)
await page.goto(login_url, wait_until=“networkidle”, timeout=40000)
await page.wait_for_timeout(3000)

```
email_input = await page.wait_for_selector(
    'input[type="email"], input[name="email"], input[name="username"]',
    timeout=15000
)
await email_input.fill(EMAIL)

next_btn = await page.query_selector('button:has-text("Next"), button:has-text("Continue")')
if next_btn:
    await next_btn.click()
    await page.wait_for_timeout(3000)
    try:
        first_item = await page.wait_for_selector('li, .team-item', timeout=5000)
        if first_item:
            await first_item.click()
            await page.wait_for_timeout(3000)
    except Exception:
        pass
else:
    await email_input.press("Tab")
    await page.wait_for_timeout(1000)

pw_input = None
for sel in ['input[type="password"]', 'input[name="password"]']:
    try:
        pw_input = await page.wait_for_selector(sel, timeout=8000)
        if pw_input:
            break
    except Exception:
        continue

if not pw_input:
    raise Exception("Could not find password field")

await pw_input.fill(PASSWORD)

btn = await page.query_selector(
    'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")'
)
if btn:
    await btn.click()
else:
    await pw_input.press("Enter")

await page.wait_for_load_state("networkidle", timeout=30000)
await page.wait_for_timeout(5000)
log(f"Logged in! URL: {page.url}")
```

async def load_open_shifts(page):
staff_url = PARIM_URL.rstrip(”/”) + “/staff”
log(f”Going to: {staff_url}”)
await page.goto(staff_url, wait_until=“networkidle”, timeout=30000)
await page.wait_for_timeout(3000)

```
open_shifts_url = PARIM_URL.rstrip("/") + "/s/event/index"
log(f"Setting iframe to: {open_shifts_url}")

await page.evaluate(f"""
    () => {{
        const iframe = document.getElementById('monolith-iframe');
        if (iframe) {{
            iframe.src = '{open_shifts_url}';
        }} else {{
            console.log('iframe not found');
        }}
    }}
""")

log("Waiting for Apply buttons to appear inside iframe...")
try:
    await page.wait_for_function("""
        () => {
            try {
                const iframe = document.getElementById('monolith-iframe');
                if (!iframe || !iframe.contentDocument) return false;
                const buttons = iframe.contentDocument.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === 'Apply') return true;
                }
                return false;
            } catch(e) {
                return false;
            }
        }
    """, timeout=20000)
    log("Apply buttons found inside iframe!")
except Exception as e:
    log(f"Wait for Apply buttons timed out: {e}")
    log("Continuing anyway after 10 second wait...")
    await page.wait_for_timeout(10000)

await page.screenshot(path="screenshot_01_open_shifts.png")
```

async def apply_for_shifts(page, applied):
count = 0

```
shifts_info = await page.evaluate("""
    () => {
        try {
            const iframe = document.getElementById('monolith-iframe');
            if (!iframe || !iframe.contentDocument) return [];
            const buttons = Array.from(iframe.contentDocument.querySelectorAll('button'));
            const applyBtns = buttons.filter(b => b.textContent.trim() === 'Apply');
            return applyBtns.map((btn, i) => {
                const row = btn.closest('tr') || btn.parentElement?.parentElement;
                return {
                    index: i,
                    text: row ? row.innerText.trim().substring(0, 200) : 'shift_' + i
                };
            });
        } catch(e) {
            return [];
        }
    }
""")

log(f"Found {len(shifts_info)} Apply button(s) via contentDocument")

if not shifts_info:
    log("No available shifts to apply for")
    return 0

for shift in shifts_info:
    shift_id = shift['text']
    shift_idx = shift['index']

    if shift_id in applied:
        log(f"Already applied - skipping")
        continue

    log(f"Applying for: {shift_id[:80]}...")

    clicked = await page.evaluate(f"""
        () => {{
            try {{
                const iframe = document.getElementById('monolith-iframe');
                if (!iframe || !iframe.contentDocument) return 'no iframe';
                const buttons = Array.from(iframe.contentDocument.querySelectorAll('button'));
                const applyBtns = buttons.filter(b => b.textContent.trim() === 'Apply');
                if (applyBtns[{shift_idx}]) {{
                    applyBtns[{shift_idx}].click();
                    return 'clicked';
                }}
                return 'button not found';
            }} catch(e) {{
                return 'error: ' + e.message;
            }}
        }}
    """)
    log(f"Click result: {clicked}")

    await page.wait_for_timeout(3000)
    await page.screenshot(path=f"screenshot_02_modal_{shift_idx}.png")

    confirmed = await page.evaluate("""
        () => {
            try {
                const iframe = document.getElementById('monolith-iframe');
                if (!iframe || !iframe.contentDocument) return 'no iframe';
                const doc = iframe.contentDocument;
                const selectors = [
                    '.modal button',
                    '[role="dialog"] button',
                    '.modal-footer button',
                    '.modal-body ~ .modal-footer button'
                ];
                for (const sel of selectors) {
                    const btns = Array.from(doc.querySelectorAll(sel));
                    const applyBtn = btns.find(b => b.textContent.trim() === 'Apply');
                    if (applyBtn) {
                        applyBtn.click();
                        return 'confirmed via ' + sel;
                    }
                }
                const allBtns = Array.from(doc.querySelectorAll('button'));
                const visibleApply = allBtns.find(b =>
                    b.textContent.trim() === 'Apply' && b.offsetParent !== null
                );
                if (visibleApply) {
                    visibleApply.click();
                    return 'confirmed via visible button';
                }
                return 'no confirm button found';
            } catch(e) {
                return 'error: ' + e.message;
            }
        }
    """)
    log(f"Confirm result: {confirmed}")

    await page.wait_for_timeout(3000)

    if "confirmed" in confirmed or "clicked" in confirmed:
        applied.add(shift_id)
        save_applied(applied)
        count += 1
        log(f"SUCCESS - Applied for shift!")
        await page.screenshot(path=f"screenshot_03_success_{shift_idx}.png")
    else:
        log(f"Could not confirm - result was: {confirmed}")

return count
```

async def main():
if not EMAIL or not PASSWORD:
log(“PARIM_EMAIL or PARIM_PASSWORD not set!”)
sys.exit(1)

```
log("PARiM Auto-Apply Bot - Starting")
applied = load_applied()
log(f"History: {len(applied)} previously-applied shifts")

from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
    )
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    page = await context.new_page()

    try:
        await login(page)
        await load_open_shifts(page)
        n = await apply_for_shifts(page, applied)
        if n:
            log(f"SUCCESS - Applied for {n} new shift(s)!")
        else:
            log("Run complete - no new shifts to apply for")
    except Exception as e:
        log(f"Error: {e}")
        try:
            await page.screenshot(path="screenshot_error.png")
        except Exception:
            pass
        sys.exit(1)
    finally:
        await browser.close()
```

if **name** == “**main**”:
asyncio.run(main())
