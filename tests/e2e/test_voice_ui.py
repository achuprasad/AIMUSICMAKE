"""Browser tests of the Malayalam Voice Studio page. The test server runs the voice worker's stand-in synthesiser
(MIXLUMO_VOICE_FAKE=1, set in tests/conftest.py) with a temporary voice folder."""
import numpy as np
import pytest
import soundfile as sf
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e
ML = "ഇന്ന് നല്ല കാലാവസ്ഥയാണ്, നമുക്ക് പുറത്ത് നടക്കാൻ പോകാം."


def open_voice(page, app_url):
    page.goto(app_url)
    page.click('nav button[data-page="voice"]')
    expect(page.locator("#page-voice h1")).to_have_text("Malayalam Voice Studio")
    expect(page.locator("#vsStatus")).to_contain_text("Test mode")


def test_page_controls_and_tones(page, app_url, errors):
    open_voice(page, app_url)
    assert page.locator("#vsTone option").count() == 17                        # 13 presets + 4 story tones
    expect(page.locator("#vsTone option").first).to_have_text("Neutral · സാധാരണ")
    expect(page.locator("#vsGo")).to_be_disabled()
    expect(page.locator("#vsLic")).to_contain_text("CC-BY-NC")
    expect(page.locator("#vsLic")).to_contain_text("Boson AI")
    page.select_option("#vsTone", "angry")
    expect(page.locator("#vsToneHint")).to_contain_text("Approximate")
    page.select_option("#vsTone", "whisper")
    expect(page.locator("#vsToneHint")).to_contain_text("real whisper")
    assert not errors


def test_tag_insert_and_character_detection(page, app_url):
    open_voice(page, app_url)
    page.fill("#vsScript", "ശരി.")
    page.locator("#vsScript").evaluate("el => el.setSelectionRange(0, 0)")
    page.select_option("#vsTag", "[angry]")
    expect(page.locator("#vsScript")).to_have_value("[angry] ശരി.")
    page.click("#vsExample")
    expect(page.locator('#vsCast select[data-name="രാമേട്ടൻ"]')).to_have_value("builtin-male-adult")
    expect(page.locator('#vsCast select[data-name="voice"]')).to_have_value("builtin-female-young")
    expect(page.locator("#vsGo")).to_be_enabled()


def test_speak_story_play_and_regenerate_a_line(page, app_url, errors):
    open_voice(page, app_url)
    page.fill("#vsScript", 'അവന്റെ പേര് തീപ്പൊരി!\n[angrily] രാമേട്ടൻ: "എന്താടാ ഇത്?"\n[whispers] പക്ഷേ ഇന്നും ഒരു രഹസ്യമുണ്ട്...')
    expect(page.locator('#vsCast select[data-name="രാമേട്ടൻ"]')).to_be_visible()
    page.click("#vsGo")
    expect(page.locator("#vsRes")).to_contain_text("Your Malayalam speech is ready", timeout=90_000)
    lines = page.locator(".vs-line")
    expect(lines).to_have_count(3)
    expect(lines.nth(1)).to_contain_text("Male, adult (deep)")
    expect(lines.nth(1).locator(".badge")).to_have_text("approximate")
    expect(lines.nth(2).locator(".badge")).to_have_text("real tone")          # built-in whisper is real
    expect(page.locator("#vsRes")).to_contain_text("AI-generated speech")
    lines.nth(0).locator(".play").click()
    lines.nth(1).locator("[data-regen]").click()
    expect(page.locator(".toast, #toast")).to_contain_text("Line 2 spoken again", timeout=60_000)
    expect(page.locator(".vs-line")).to_have_count(3)
    assert not errors


def test_english_is_refused_with_a_clear_message(page, app_url):
    open_voice(page, app_url)
    page.fill("#vsScript", "Hello, this is English text.")
    page.click("#vsGo")
    expect(page.locator("#vsProg .alert")).to_contain_text("Malayalam only", timeout=30_000)


def test_add_rename_and_delete_a_voice(page, app_url, tmp_path, errors):
    t = np.arange(24000 * 5) / 24000
    wav = tmp_path / "me.wav"
    sf.write(wav, (0.2 * np.sin(2 * np.pi * 180 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t))).astype(np.float32), 24000)
    open_voice(page, app_url)
    expect(page.locator("#vcGo")).to_be_disabled()
    page.set_input_files("#vcFile", str(wav))
    page.fill("#vcName", "Test voice")
    page.fill("#vcText", ML)
    expect(page.locator("#vcGo")).to_be_disabled()                             # consent first
    page.check("#vcConsent")
    expect(page.locator("#vcGo")).to_be_enabled()
    page.click("#vcGo")
    item = page.locator(".voice-item", has_text="Test voice")
    expect(item).to_be_visible(timeout=60_000)
    expect(page.locator("#vsVoice")).to_contain_text("Test voice")
    page.once("dialog", lambda d: d.accept("Renamed voice"))
    item.locator("[data-rename]").click()
    expect(page.locator(".voice-item", has_text="Renamed voice")).to_be_visible()
    page.once("dialog", lambda d: d.accept())
    page.locator(".voice-item", has_text="Renamed voice").locator("[data-del]").click()
    expect(page.locator(".voice-item", has_text="Renamed voice")).to_have_count(0)
    assert not errors


def test_voice_page_on_a_phone(page, app_url):
    page.set_viewport_size({"width": 375, "height": 812})
    open_voice(page, app_url)
    page.click("#vsExample")
    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert over <= 1, f"voice page overflows by {over}px on a phone"
