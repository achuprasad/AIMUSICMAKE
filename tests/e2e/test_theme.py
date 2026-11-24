"""Themes (light / dark / auto), accent colours, readable contrast and the copyright notice."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

CONTRAST_JS = """([fg, bg]) => {
  const v = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const lum = h => { const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
    const ch = i => parseInt(h.slice(i, i + 2), 16);
    return 0.2126 * f(ch(1)) + 0.7152 * f(ch(3)) + 0.0722 * f(ch(5)); };
  const a = lum(v(fg)), b = lum(v(bg));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}"""


def bg_luminance(page):
    return page.evaluate("""() => { const m = getComputedStyle(document.body).backgroundColor.match(/\\d+/g).map(Number);
                             return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255; }""")


def theme(page):
    return page.evaluate("document.documentElement.getAttribute('data-theme')")


def test_switch_theme_and_remember_it(page, app_url, errors):
    page.goto(app_url)
    page.click('#themeSeg button[data-v="light"]')
    assert theme(page) == "light" and bg_luminance(page) > 0.9
    expect(page.locator('#themeSeg button[data-v="light"]')).to_have_attribute("aria-pressed", "true")
    page.reload()
    assert theme(page) == "light" and bg_luminance(page) > 0.9  # remembered, applied before first paint
    page.click('#themeSeg button[data-v="dark"]')
    assert theme(page) == "dark" and bg_luminance(page) < 0.1
    assert not errors


@pytest.mark.parametrize("scheme,light", [("light", True), ("dark", False)])
def test_auto_follows_windows_setting(page, app_url, scheme, light):
    page.emulate_media(color_scheme=scheme)
    page.goto(app_url)
    page.click('#themeSeg button[data-v="system"]')
    assert theme(page) == "system"
    assert (bg_luminance(page) > 0.9) is light


def test_accent_presets_and_custom_colour(page, app_url):
    page.goto(app_url)
    page.click('#accentSw .swatch[aria-label="Teal accent"]')
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == "#0d9488"
    expect(page.locator('#accentSw .swatch[aria-label="Teal accent"]')).to_have_attribute("aria-pressed", "true")
    page.evaluate("""() => { const i = document.querySelector('#accentCustom'); i.value = '#ff00aa';
                     i.dispatchEvent(new Event('input', {bubbles: true})); }""")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == "#ff00aa"
    page.reload()
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()") == "#ff00aa"


def test_light_accent_gets_dark_button_text(page, app_url):
    page.goto(app_url)
    page.evaluate("""() => { const i = document.querySelector('#accentCustom'); i.value = '#ffe066';
                     i.dispatchEvent(new Event('input', {bubbles: true})); }""")
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--on-accent').trim()") == "#111111"


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("accent", ["Violet", "Blue", "Teal", "Green", "Orange", "Pink", "Red"])
def test_text_contrast_meets_wcag_aa(page, app_url, mode, accent):
    page.goto(app_url)
    page.click(f'#themeSeg button[data-v="{mode}"]')
    page.click(f'#accentSw .swatch[aria-label="{accent} accent"]')
    checks = {("--text", "--bg"): 7.0, ("--text", "--surface"): 7.0, ("--muted", "--surface"): 4.5,
              ("--muted", "--surface-2"): 4.5, ("--accent-text", "--surface"): 4.5, ("--err-text", "--surface"): 4.5,
              ("--ok-text", "--surface"): 4.5}
    for (fg, bg), minimum in checks.items():
        ratio = page.evaluate(CONTRAST_JS, [fg, bg])
        assert ratio >= minimum, f"{mode}/{accent}: {fg} on {bg} = {ratio:.2f} (< {minimum})"


def test_every_page_renders_in_light_theme(page, app_url, errors):
    page.goto(app_url)
    page.click('#themeSeg button[data-v="light"]')
    for name in ("split", "pitch", "analyze", "cut", "join", "convert", "support"):
        page.click(f'nav button[data-page="{name}"]')
        expect(page.locator(f"#page-{name}")).to_be_visible()
        # card text must not be the dark theme's near-white on a white card
        h1 = page.evaluate("() => getComputedStyle(document.querySelector('.page.active h1')).color")
        assert h1 != "rgb(231, 234, 240)"
    assert not errors


@pytest.mark.parametrize("w", [320, 375])
def test_no_sideways_scroll_with_wcag_text_spacing(page, app_url, w):
    """Regression (found by CI on Linux, whose fonts are wider): Help & Feedback overflowed 8 px at 375 px.
    WCAG 1.4.12 text spacing makes text wider on every OS, so this catches it on Windows too."""
    page.set_viewport_size({"width": w, "height": 800})
    page.goto(app_url)
    page.add_style_tag(content="*{letter-spacing:.12em!important;word-spacing:.16em!important;line-height:1.5!important}")
    for name in ("split", "pitch", "analyze", "cut", "join", "convert", "support"):
        page.click(f'nav button[data-page="{name}"]')
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert over <= 1, f"{name} overflows by {over}px at {w}px with WCAG text spacing"


def test_brand_and_search_tags(page, app_url):
    page.goto(app_url)
    meta = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('meta[name], meta[property]')]
                             .map(m => [m.getAttribute('name') || m.getAttribute('property'), m.content]))""")
    assert "vocal remover" in meta["description"].lower() and len(meta["description"]) <= 200
    assert meta["og:title"].startswith("Mixlumo") and meta["application-name"] == "Mixlumo"
    expect(page.locator(".brand b")).to_have_text("Mixlumo")
    expect(page.locator("#appVersion")).to_have_text("1.2.1")


def test_copyright_notice_is_visible(page, app_url):
    page.goto(app_url)
    expect(page.locator(".legal")).to_contain_text("© 2026 Achu Prasad. All rights reserved.")
    page.click('nav button[data-page="support"]')
    about = page.locator("details.faq").filter(has=page.locator("summary", has_text="About & licences"))
    expect(about).to_contain_text("© 2026 Achu Prasad. All rights reserved.")
