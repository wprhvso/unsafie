import contextlib
import json
import random
import string
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from unsafie.cli import browser
from unsafie.cli import email as email_cli


def _random_email() -> str:
    name = "".join(random.choices(string.ascii_lowercase, k=8))
    return f"{name}@unsafie.com"


def generate(
    prompt: str = "Create a photo of a cute cat",
    output: str | Path | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    email = _random_email()
    browser.start()
    try:
        browser.goto("https://chatgpt.com")
        time.sleep(4)

        browser.evaluate(
            '(() => { const b = Array.from(document.querySelectorAll("button, a")).find(el => /accept all|принять все|accept/i.test(el.innerText || "")); if (b) b.click(); })()'
        )
        time.sleep(1)

        browser.click(".wm-app-signupButton")
        time.sleep(3)

        browser.click('[id="mobile-auth-email"]')
        time.sleep(1)
        browser.type_text('[id="mobile-auth-email"]', email)
        time.sleep(1)
        browser.click('form[data-auth-provider="email"] [type="submit"]')
        time.sleep(3)

        code = "0"
        poll_deadline = time.monotonic() + 90.0
        while time.monotonic() < poll_deadline:
            time.sleep(2)
            c = email_cli.get_code(email)
            if c and c != "0":
                code = c
                break

        if code == "0":
            msg = "did not receive email verification code in time"
            raise RuntimeError(msg)

        browser.type_text('[inputmode="numeric"]', code)
        time.sleep(1)
        browser.evaluate(
            f"""(() => {{
            const code = {json.dumps(code)};
            const inputs = document.querySelectorAll("[inputmode=\\"numeric\\"]");
            if (inputs.length > 1) {{
                for (let i = 0; i < inputs.length && i < code.length; i++) {{
                    inputs[i].value = code[i];
                    inputs[i].dispatchEvent(new Event("input", {{bubbles: true}}));
                    inputs[i].dispatchEvent(new Event("change", {{bubbles: true}}));
                }}
            }}
        }})()"""
        )
        time.sleep(1)
        browser.click('[data-dd-action-name="Continue"]')

        name_deadline = time.monotonic() + 15.0
        while time.monotonic() < name_deadline:
            time.sleep(1)
            has_name = browser.evaluate(
                '!!document.querySelector(\'[name="name"]\')'
            ).get("result")
            if has_name:
                browser.click('[name="name"]')
                time.sleep(0.5)
                browser.type_text('[name="name"]', "Full Name")
                time.sleep(0.5)
                browser.evaluate("""(() => {
                    const el = document.querySelector('[name="name"]');
                    if (el) {
                        el.value = "Full Name";
                        el.dispatchEvent(new Event("input", {bubbles: true}));
                        el.dispatchEvent(new Event("change", {bubbles: true}));
                    }
                })()""")
                time.sleep(0.5)

                browser.click('[inputmode="numeric"]')
                time.sleep(0.5)
                browser.type_text('[inputmode="numeric"]', "18")
                time.sleep(0.5)
                browser.evaluate("""(() => {
                    const el = document.querySelector('[inputmode="numeric"]');
                    if (el) {
                        el.value = "18";
                        el.dispatchEvent(new Event("input", {bubbles: true}));
                        el.dispatchEvent(new Event("change", {bubbles: true}));
                    }
                })()""")
                time.sleep(0.5)

                browser.click('[type="submit"]')
                time.sleep(3)
                break

        set_deadline = time.monotonic() + 20.0
        while time.monotonic() < set_deadline:
            time.sleep(1)
            res = browser.evaluate("""(() => {
                const btns = Array.from(document.querySelectorAll("button, a, [role=\"button\"]"));
                for (const b of btns) {
                    const t = (b.innerText || b.textContent || "").trim().toLowerCase();
                    if (t === "continue" || t.includes("continue") || t.includes("продолжить")) {
                        b.scrollIntoView({block: "center"});
                        b.click();
                        return true;
                    }
                }
                return false;
            })()""").get("result")
            if res:
                time.sleep(4)
                break

        browser.goto("https://chatgpt.com")
        time.sleep(5)

        browser.evaluate("""(() => {
            document.querySelectorAll("dialog[open]").forEach(d => d.close());
            const closeBtns = Array.from(document.querySelectorAll("button")).filter(b => /got it|dismiss|next|done|close|понятно|закрыть|okay|stay logged out/i.test(b.innerText || ""));
            for (const b of closeBtns) b.click();
        })()""")
        time.sleep(1)

        for _ in range(5):
            browser.press("escape")
            time.sleep(0.3)

        browser.evaluate("""(() => {
            const el = document.querySelector('[id="prompt-textarea"], textarea, div[contenteditable="true"]');
            if (el) el.scrollIntoView({block: "center"});
        })()""")

        browser.click('[id="prompt-textarea"]')
        time.sleep(1)
        browser.type_text('[id="prompt-textarea"]', prompt)
        time.sleep(1)

        intercept_proc = subprocess.Popen(
            [
                "unsafie",
                "browser",
                "intercept",
                "*estuary/content*",
                "--no-block",
                "--timeout",
                str(timeout),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(2)

        browser.press("enter")
        time.sleep(1)
        browser.evaluate("""(() => {
            const sendBtn = document.querySelector('[data-testid="send-button"], button[aria-label*="Send"], button[aria-label*="Отправить"], [id="composer-background"] button:last-child');
            if (sendBtn && !sendBtn.disabled) sendBtn.click();
        })()""")

        stdout, stderr = intercept_proc.communicate()
        try:
            intercept_data = json.loads(stdout.strip())
        except Exception:
            msg = f"failed to intercept image request: {stdout or stderr}"
            raise RuntimeError(msg) from None

        intercept_url = intercept_data.get("url")
        req_headers = intercept_data.get("headers", {})
        if not intercept_url:
            msg = f"no image url intercepted: {stdout or stderr}"
            raise RuntimeError(msg)

        req = urllib.request.Request(intercept_url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()

        if output is not None:
            target = Path(output)
            if target.is_dir():
                target = target / f"image_{int(time.time() * 1000)}.png"
        else:
            target = Path(f"/tmp/shots/image_{int(time.time() * 1000)}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

        return {
            "ok": True,
            "path": str(target),
            "url": intercept_url,
            "bytes": len(data),
            "email": email,
            "prompt": prompt,
        }
    finally:
        with contextlib.suppress(Exception):
            browser.stop()
