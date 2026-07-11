"""Playwright smoke test: load app, verify prediction renders, swap Haaland out,
assert the number moves. Server must be running on :8097."""
import re

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8097"


def pct_of(page, selector):
    txt = page.locator(selector).inner_text()
    return float(re.search(r"([\d.]+)%", txt).group(1))


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#results", state="visible", timeout=10000)
    page.wait_for_timeout(500)

    assert "England" in page.locator("#hero .side.a").inner_text()
    assert "Norway" in page.locator("#hero .side.b").inner_text()
    eng_before = pct_of(page, "#hero .side.a")
    nor_before = pct_of(page, "#hero .side.b")
    assert abs(eng_before + nor_before - 100) < 1.5, "advance percentages sum to ~100"
    print(f"ok - default prediction renders: England {eng_before}% / Norway {nor_before}%")

    sections = page.locator("#analysis .card").count()
    assert sections == 8, f"expected 8 analysis sections, got {sections}"
    assert "Elo" in page.locator("#analysis").inner_text()
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

    assert not errors, f"JS errors: {errors}"
    page.screenshot(path="data/cache/smoke.png", full_page=True)
    print("ok - no JS errors; screenshot at data/cache/smoke.png")
    browser.close()

print("\nsmoke test passed")
