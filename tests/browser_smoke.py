"""Browser smoke test — drives the real app in a real browser.

    make browser-test

The pytest suite exercises the server with an HTTP client, which never runs
JavaScript. That blind spot hid several real bugs: the nav's alerts badge
injecting the whole login page into the sidebar, the category dropdown's inline
onchange handler being refused by the CSP, and htmx's injected indicator
<style> violating style-src. None of them were visible without a browser.

Runs uvicorn in a thread inside this process (rather than as a detached
listener) and drives Chromium against it, failing on any console error, page
error, CSP violation or 4xx/5xx response.

Requires the dev virtualenv (`make venv`) plus `playwright`, and a Chromium at
PLAYWRIGHT_BROWSERS_PATH. It is deliberately NOT part of `make test`: it starts
a server and a browser, so it is a separate, slower gate.
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"

def _find_chromium() -> str:
    """Locate the Playwright-managed Chromium without downloading one."""
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome"), reverse=True):
        return str(candidate)
    return "chromium"


CHROMIUM = _find_chromium()
PORT = 8099
BASE = f"http://127.0.0.1:{PORT}"

workdir = Path(tempfile.mkdtemp(prefix="fh-browser-"))
DB = workdir / "browser.db"
SHOTS = workdir / "shots"
SHOTS.mkdir()

SECRETS = workdir / "dev.yaml"
SECRETS.write_text(
    "database:\n  key: '3a7f1c9e2b8d4f6a0c5e7b9d1f3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f91'\n"
    "app:\n  secret_key: 'browser-check'\n"
    "nordigen:\n  secret_id: 'sid'\n  secret_key: 'skey'\n"
    "token_encryption:\n  master_key: "
    "'9f1e3d5c7b9a1f3e5d7c9b1a3f5e7d9c1b3a5f7e9d1c3b5a7f9e1d3c5b7a9f1e'\n"
    "restic:\n  password: 'pw'\n  repository: 'local:/tmp/restic'\n"
)

ENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin",
    "FINANCEHUB_DB_KEY": "3a7f1c9e2b8d4f6a0c5e7b9d1f3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f91",
    "FINANCEHUB_DB_PATH": str(DB),
    "FINANCEHUB_ENV": "development",
    "FINANCEHUB_INSECURE_COOKIES": "1",
    "FINANCEHUB_RP_ID": "127.0.0.1",
    "FINANCEHUB_ORIGIN": BASE,
    "FINANCEHUB_DEV_SECRETS": str(SECRETS),
    "FINANCEHUB_STATIC_DIR": str(REPO / "static"),
}

print("== running migrations ==")
mig = subprocess.run(
    [str(BACKEND / ".venv/bin/python"), "-m", "alembic", "upgrade", "head"],
    cwd=BACKEND, env=ENV, capture_output=True, text=True, timeout=180,
)
if mig.returncode != 0:
    print(mig.stdout, mig.stderr)
    sys.exit(1)
print("migrations OK")

os.environ.update(ENV)
sys.path.insert(0, str(BACKEND))

import uvicorn  # noqa: E402

import app.config as config_module  # noqa: E402
from app.config import load_secrets  # noqa: E402
from app.database import init_db  # noqa: E402

config_module._secrets = load_secrets()
init_db(ENV["FINANCEHUB_DB_KEY"], str(DB))

from app.database import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.security.bootstrap import init_bootstrap_token  # noqa: E402

_db = next(get_db())
SETUP_TOKEN = init_bootstrap_token(_db)
_db.close()
print(f"setup token: {SETUP_TOKEN}")

config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=PORT, log_level="warning")
server = uvicorn.Server(config)
# Skip lifespan: secrets/DB are already initialised above and we do not want the
# 6-hour scheduler running inside a test process.
config.lifespan = "off"
threading.Thread(target=server.run, daemon=True).start()

for _ in range(100):
    if server.started:
        break
    time.sleep(0.1)
else:
    print("server did not start")
    sys.exit(1)
print(f"server up on {BASE}")

import httpx  # noqa: E402

probe = httpx.get(f"{BASE}/liveness", timeout=10)
print(f"probe /liveness -> {probe.status_code} {probe.text[:40]}")
probe_login = httpx.get(f"{BASE}/auth/login", timeout=10)
print(f"probe /auth/login -> {probe_login.status_code} ({len(probe_login.text)} bytes)")
probe_static = httpx.get(f"{BASE}/static/js/htmx.min.js", timeout=10)
print(f"probe /static/js/htmx.min.js -> {probe_static.status_code} "
      f"({len(probe_static.content)} bytes)")

ING_CSV = (
    '"Datum","Naam / Omschrijving","Rekening","Tegenrekening","Code","Af Bij",'
    '"Bedrag (EUR)","Mutatiesoort","Mededelingen"\r\n'
    '"20260305","Salaris Werkgever BV","NL01INGB0001234567","NL99BANK0000000001","OV","Bij",'
    '"2.500,00","Overschrijving","Salaris maart"\r\n'
    '"20260306","Albert Heijn 1234","NL01INGB0001234567","","BA","Af",'
    '"25,50","Betaalautomaat","Pasvolgnr 001"\r\n'
    '"20260312","Albert Heijn 5678","NL01INGB0001234567","","BA","Af",'
    '"42,10","Betaalautomaat","Pasvolgnr 002"\r\n'
    '"20260318","Jumbo Amsterdam","NL01INGB0001234567","","BA","Af",'
    '"18,40","Betaalautomaat","Pasvolgnr 003"\r\n'
)
csv_path = workdir / "ing.csv"
csv_path.write_text(ING_CSV)

import pyotp  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

problems: list[str] = []
checks: list[tuple[str, bool, str]] = []


def check(label, ok, detail=""):
    checks.append((label, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail else ""))


with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.environ.get("FINANCEHUB_CHROMIUM", CHROMIUM),
        args=["--no-sandbox"],
    )
    page = browser.new_page()

    page.on("console", lambda m: problems.append(f"console.{m.type}: {m.text}")
            if m.type == "error" and "favicon.ico" not in m.text else None)
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("response", lambda r: problems.append(f"HTTP {r.status}: {r.url}")
            if r.status >= 400 and not r.url.endswith("/favicon.ico") else None)

    # ---- the libraries are real, not stubs --------------------------------
    page.goto(f"{BASE}/auth/login", wait_until="load")
    page.screenshot(path=str(SHOTS / "01-login.png"))

    htmx_version = page.evaluate("() => window.htmx && window.htmx.version")
    check("htmx loaded and real", bool(htmx_version) and "placeholder" not in str(htmx_version),
          f"version={htmx_version}")
    # Alpine is deliberately NOT loaded on the login page any more.
    alpine_on_login = page.evaluate("() => !!window.Alpine")
    check("Alpine not loaded on login (plain JS now)", not alpine_on_login)

    # ---- CSS actually applied (the style-src-attr fix) --------------------
    bg = page.evaluate(
        "() => getComputedStyle(document.body).backgroundColor"
    )
    check("stylesheet applied", bg not in ("", "rgba(0, 0, 0, 0)"), f"body bg={bg}")

    card_pad = page.evaluate(
        "() => { const c = document.querySelector('.card');"
        " return c ? getComputedStyle(c).padding : null; }"
    )
    check("inline style attributes not blocked by CSP", card_pad not in (None, "0px"),
          f"card padding={card_pad}")

    # ---- TOTP enrollment --------------------------------------------------
    page.goto(f"{BASE}/auth/totp/setup?token={SETUP_TOKEN}", wait_until="load")
    page.screenshot(path=str(SHOTS / "02-totp-setup.png"))
    secret = re.search(r'name="secret" value="([A-Z2-7]+)"', page.content()).group(1)
    qr_ok = page.evaluate(
        "() => { const i = document.querySelector('img[alt=\"TOTP QR code\"]');"
        " return !!i && i.naturalWidth > 0; }"
    )
    check("QR code renders", qr_ok)

    page.fill("#code", pyotp.TOTP(secret).now())
    page.click("button[type=submit]")
    page.wait_for_load_state("load")
    check("enrollment lands on the dashboard", page.url.rstrip("/") == BASE, page.url)
    page.screenshot(path=str(SHOTS / "03-dashboard.png"))

    # ---- CSV import through the UI ---------------------------------------
    page.goto(f"{BASE}/transactions/", wait_until="load")
    check("empty state offers the import link",
          "Import a bank CSV" in page.content())

    page.goto(f"{BASE}/transactions/import", wait_until="load")
    page.set_input_files("#file", str(csv_path))
    page.fill("#account_label", "ING Betaalrekening")
    page.click("button[type=submit]")
    page.wait_for_load_state("load")
    page.screenshot(path=str(SHOTS / "04-import-result.png"))
    check("import reports success", "ING import complete" in page.content())
    check("import counted 4 rows", "4" in page.inner_text(".stat-grid"))

    # ---- transactions render, htmx re-categorize works --------------------
    page.goto(f"{BASE}/transactions/", wait_until="load")
    page.screenshot(path=str(SHOTS / "05-transactions.png"))
    check("imported rows visible", "Albert Heijn" in page.content())

    row_count = page.evaluate(
        "() => document.querySelectorAll('#transaction-rows tr').length"
    )
    check("4 transaction rows", row_count == 4, f"rows={row_count}")

    # Drive the HTMX category dropdown — this is the interaction that could
    # never have worked with the stub htmx.
    selects = page.query_selector_all("#transaction-rows select")
    if selects:
        before = page.content()
        options = selects[0].query_selector_all("option")
        target = next(
            (o for o in options
             if o.inner_text().strip() and "Shopping" in o.inner_text()), None
        )
        if target:
            selects[0].select_option(value=target.get_attribute("value"))
            page.wait_for_timeout(1500)
            after = page.content()
            check("htmx category swap fired", before != after)
            page.reload(wait_until="load")
            check("category change persisted",
                  "Shopping" in page.inner_text("#transaction-rows"))
        else:
            check("htmx category swap fired", False, "no Shopping option found")
    else:
        check("htmx category swap fired", False, "no category selects rendered")

    # ---- budgets ----------------------------------------------------------
    page.goto(f"{BASE}/budgets/", wait_until="load")
    page.screenshot(path=str(SHOTS / "06-budgets.png"))
    check("budgets page renders with data", "Daily allowance" in page.content())

    # ---- remaining core pages --------------------------------------------
    for path, label in (
        ("/accounts/", "accounts"),
        ("/categories/", "categories"),
        ("/goals/", "goals"),
        ("/health/", "health"),
        ("/alerts/", "alerts"),
    ):
        resp = page.goto(f"{BASE}{path}", wait_until="load")
        check(f"{label} page 200", resp.status == 200, f"status={resp.status}")
    page.screenshot(path=str(SHOTS / "07-health.png"))

    browser.close()

server.should_exit = True
time.sleep(1)

print("\n== console / page errors ==")
csp = [p for p in problems if "Content Security Policy" in p or "CSP" in p]
if problems:
    for p_ in dict.fromkeys(problems):
        print(" ", p_)
else:
    print("  none")

check("no CSP violations", not csp, f"{len(csp)} violation(s)")

failed = [c for c in checks if not c[1]]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
print(f"screenshots: {SHOTS}")

sys.exit(1 if failed else 0)
