"""Playwright smoke test: load app, verify prediction renders, swap Haaland out,
assert the number moves, and check permalinks + share. Server must be running
on :8097 (or set FOOTBALL_BASE=https://...)."""
import os
import re

from playwright.sync_api import sync_playwright

BASE = os.environ.get("FOOTBALL_BASE", "http://localhost:8097")


def pct_of(page, selector):
    txt = page.locator(selector).inner_text()
    return float(re.search(r"([\d.]+)%", txt).group(1))


def wait_results(page):
    page.wait_for_selector("#results", state="visible", timeout=10000)
    page.wait_for_timeout(600)


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                              permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    wait_results(page)

    assert "England" in page.locator("#hero .side.a").inner_text()
    assert "Norway" in page.locator("#hero .side.b").inner_text()
    eng_before = pct_of(page, "#hero .side.a")
    nor_before = pct_of(page, "#hero .side.b")
    assert abs(eng_before + nor_before - 100) < 1.5, "advance percentages sum to ~100"
    assert page.url.rstrip("/").endswith("england-vs-norway"), "default URL is the matchup permalink"
    print(f"ok - default prediction renders: England {eng_before}% / Norway {nor_before}%")

    sections = page.locator("#analysis .card").count()
    assert sections == 8, f"expected 8 analysis sections, got {sections}"
    print("ok - 8 analysis sections with prose")

    # bench Haaland for the top bench forward
    page.locator("#pitch-B .slot", has_text="Haaland").click()
    page.wait_for_selector("#overlay", state="visible")
    page.locator("#picker-body .prow:not(.selected)", has_text="Strand Larsen").click()
    page.wait_for_timeout(700)
    eng_after = pct_of(page, "#hero .side.a")
    assert eng_after > eng_before + 1, f"England should gain >1pt ({eng_before} -> {eng_after})"
    print(f"ok - benching Haaland moves the number: England {eng_before}% -> {eng_after}%")

    # formation switch keeps a legal XI
    page.select_option("#formation-B", "4-4-2")
    page.wait_for_timeout(700)
    assert page.locator("#pitch-B .slot").count() == 11
    assert "⚠" not in page.locator("#spin").inner_text()
    print("ok - formation switch keeps 11 players and predicts cleanly")

    # permalink round-trip: URL encodes the edited selection and reproduces it
    url = page.url
    assert "england-vs-norway" in url and "fb=4-4-2" in url and "xb=" in url, url
    eng_now = pct_of(page, "#hero .side.a")
    page.goto(url, wait_until="networkidle")
    wait_results(page)
    assert abs(pct_of(page, "#hero .side.a") - eng_now) < 0.5, "reloaded permalink reproduces the %"
    assert page.locator("#formation-B").input_value() == "4-4-2"
    assert "England vs Norway" in page.title()
    print("ok - permalink round-trip reproduces edited lineup")

    # matchup permalink
    page.goto(f"{BASE}/france-vs-spain", wait_until="networkidle")
    wait_results(page)
    assert "France" in page.locator("#hero .side.a").inner_text()
    assert "Spain" in page.locator("#hero .side.b").inner_text()
    print("ok - /france-vs-spain loads that matchup")

    # share button copies the permalink (no navigator.share in headless desktop)
    page.click("#share")
    page.wait_for_timeout(300)
    assert "copied" in page.locator("#share").inner_text().lower()
    clip = page.evaluate("navigator.clipboard.readText()")
    assert clip == page.url, f"clipboard {clip} != {page.url}"
    print("ok - share button copies the permalink")

    assert not errors, f"JS errors: {errors}"
    page.screenshot(path="data/cache/smoke.png", full_page=True)
    print("ok - no JS errors; screenshot at data/cache/smoke.png")
    browser.close()

print("\nsmoke test passed")
