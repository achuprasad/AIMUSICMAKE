"""Browser end-to-end tests (Playwright). Run with --browser chromium --browser firefox."""
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

PAGES = {"split": "Vocal Remover & Stem Splitter", "pitch": "Pitch & Tempo Changer", "analyze": "Key & BPM Finder",
         "cut": "Audio Cutter", "join": "Audio Joiner", "convert": "Audio Converter"}


def goto(page, url, name):
    page.goto(url)
    page.click(f'nav button[data-page="{name}"]')
    expect(page.locator(f"#page-{name} h1")).to_have_text(PAGES[name])


def drop(page, name, *files):
    page.set_input_files(f'[data-drop="{name}"] input[type=file]', [str(f) for f in files])


def test_loads_and_navigates(page, app_url, errors):
    page.goto(app_url)
    expect(page).to_have_title("Local Audio Studio")
    expect(page.locator("#devname")).to_have_text("CPU mode")
    for name, title in PAGES.items():
        page.click(f'nav button[data-page="{name}"]')
        expect(page.locator(f"#page-{name}")).to_be_visible()
        expect(page.locator(f"#page-{name} h1")).to_have_text(title)
        assert page.locator(".page.active").count() == 1
    assert not errors


def test_run_button_disabled_until_upload(page, app_url):
    page.goto(app_url)
    for name in ("split", "pitch", "analyze", "cut", "convert", "join"):
        expect(page.locator(f"#{name}Go")).to_be_disabled()


def test_cut_flow(page, app_url, fixtures, errors):
    goto(page, app_url, "cut")
    drop(page, "cut", fixtures["tone_wav"])
    card = page.locator('[data-drop="cut"] .file')
    expect(card).to_contain_text("tone 440.wav")
    expect(card).to_contain_text("0:05")
    expect(page.locator("#cutRegion")).to_be_visible()
    expect(page.locator("#cutE")).to_have_value("5.0")
    page.fill("#cutS", "1")
    page.fill("#cutE", "3")
    expect(page.locator("#cutGo")).to_be_enabled()
    page.click("#cutGo")
    prog = page.locator("#cutProg")
    expect(prog).to_have_class(re.compile(r"\bdone\b"), timeout=60_000)
    expect(prog.locator(".pg-pct")).to_have_text("100%")
    expect(prog.locator(".pg-stage")).to_have_text("Completed")
    expect(prog.locator(".step.ok")).to_have_count(3)
    link = page.locator("#cutRes a[download]")
    assert link.get_attribute("href").startswith("/files/")
    assert page.request.get(page.url.rstrip("/") + link.get_attribute("href")).ok
    page.click("#cutRes .play")
    expect(page.locator("#cutRes .play rect").first).to_be_attached(timeout=5000)  # pause icon = playing
    assert not errors


def test_spoofed_upload_shows_error(page, app_url, fixtures):
    goto(page, app_url, "convert")
    drop(page, "convert", fixtures["spoofed_mp3"])
    expect(page.locator('[data-drop="convert"] .file .meta span')).to_contain_text("not a readable audio file")
    expect(page.locator("#convertGo")).to_be_disabled()


def test_remove_file_resets_dropzone(page, app_url, fixtures):
    goto(page, app_url, "convert")
    drop(page, "convert", fixtures["tone_mp3"])
    expect(page.locator("#convertGo")).to_be_enabled()
    page.click('[data-drop="convert"] .file [data-remove]')
    expect(page.locator('[data-drop="convert"] .drop')).to_be_visible()
    expect(page.locator("#convertGo")).to_be_disabled()


def test_replace_file(page, app_url, fixtures):
    goto(page, app_url, "convert")
    drop(page, "convert", fixtures["tone_mp3"])
    card = page.locator('[data-drop="convert"] .file')
    expect(card).to_contain_text("tone.mp3")
    expect(card.locator("[data-remove]")).to_have_text("Remove")
    with page.expect_file_chooser() as fc:
        card.locator("[data-replace]").click()
    with page.expect_request(lambda r: r.method == "DELETE" and "/api/uploads/" in r.url):
        fc.value.set_files(str(fixtures["mono_flac"]))
    expect(card).to_contain_text("mono22k.flac")
    expect(page.locator("#convertGo")).to_be_enabled()


def test_job_failure_state(page, app_url, fixtures):
    goto(page, app_url, "cut")
    drop(page, "cut", fixtures["tone_wav"])
    expect(page.locator("#cutGo")).to_be_enabled()
    page.fill("#cutS", "4")
    page.fill("#cutE", "2")
    page.click("#cutGo")
    prog = page.locator("#cutProg")
    expect(prog).to_have_class(re.compile(r"\berr\b"), timeout=30_000)
    expect(prog.locator(".alert")).to_contain_text("Start must be before end")
    expect(page.locator("#cutGo")).to_be_enabled()  # user can retry


def test_analyze_flow(page, app_url, fixtures):
    goto(page, app_url, "analyze")
    drop(page, "analyze", fixtures["a_major"])
    expect(page.locator("#analyzeGo")).to_be_enabled()
    page.click("#analyzeGo")
    expect(page.locator("#analyzeRes")).to_contain_text("A major", timeout=60_000)
    expect(page.locator("#analyzeRes")).to_contain_text("11B")


def test_pitch_flow(page, app_url, fixtures):
    goto(page, app_url, "pitch")
    drop(page, "pitch", fixtures["tone_wav"])
    page.locator("#st").fill("3")
    expect(page.locator("#stVal")).to_have_text("+3 semitones")
    page.click("#pitchGo")
    expect(page.locator("#pitchRes")).to_contain_text("+3 st", timeout=60_000)


def test_speed_presets_and_keep_pitch(page, app_url, fixtures, errors):
    goto(page, app_url, "pitch")
    expect(page.locator('label[for="tp"]')).to_contain_text("Speed")
    expect(page.locator("#tpVal")).to_have_text("1.00×")
    page.click('#tpPresets button[data-v="125"]')
    expect(page.locator("#tpVal")).to_have_text("1.25×")
    expect(page.locator("#tp")).to_have_value("125")
    expect(page.locator("#kpHint")).to_contain_text("same key")
    page.uncheck("#keepPitch")
    expect(page.locator("#kpHint")).to_contain_text("+3.9 semitones")
    drop(page, "pitch", fixtures["tone_wav"])
    page.click("#pitchGo")
    expect(page.locator("#pitchRes")).to_contain_text("1.25x speed tape", timeout=60_000)
    assert not errors


def test_source_player_plays_uploaded_song(page, app_url, fixtures, errors):
    goto(page, app_url, "convert")
    drop(page, "convert", fixtures["tone_wav"])
    play = page.locator('[data-drop="convert"] .preview .play')
    expect(play).to_be_visible(timeout=15_000)
    play.click()
    page.wait_for_function("SRC.convert && SRC.convert.audio.currentTime > 0.3", timeout=10_000)
    expect(page.locator('[data-drop="convert"] .preview .time')).not_to_have_text("0:00 / 0:05")
    play.click()
    page.wait_for_function("SRC.convert.audio.paused")
    assert not errors


def test_live_pitch_and_speed_preview(page, app_url, fixtures, errors):
    goto(page, app_url, "pitch")
    drop(page, "pitch", fixtures["tone_wav"])
    expect(page.locator('[data-drop="pitch"] .live-hint')).to_contain_text("Live preview", timeout=15_000)
    page.click('[data-drop="pitch"] .preview .play')
    page.wait_for_function("SRC.pitch && SRC.pitch.node && !SRC.pitch.audio.paused", timeout=10_000)
    # speed changes apply to the playing audio immediately
    page.click('#tpPresets button[data-v="125"]')
    assert page.evaluate("SRC.pitch.audio.playbackRate") == 1.25
    assert page.evaluate("SRC.pitch.audio.preservesPitch") is True
    page.uncheck("#keepPitch")
    assert page.evaluate("SRC.pitch.audio.preservesPitch") is False
    page.locator("#st").fill("3")
    assert page.evaluate("SRC.pitch.settings.semitones") == 3
    # the pitch shifter must produce real sound (not silence, not NaN)
    rms = page.evaluate("""async () => {
        const sp = SRC.pitch, an = sp.ctx.createAnalyser(); an.fftSize = 2048; sp.node.connect(an);
        await new Promise(r => setTimeout(r, 600));
        const d = new Float32Array(an.fftSize); an.getFloatTimeDomainData(d);
        let s = 0; for (const v of d) s += v * v; return Math.sqrt(s / d.length);
    }""")
    assert 0.01 < rms < 1.0, f"pitch-shifted preview RMS {rms}"
    assert not errors


def test_removing_file_stops_preview(page, app_url, fixtures):
    goto(page, app_url, "pitch")
    drop(page, "pitch", fixtures["tone_wav"])
    page.locator('[data-drop="pitch"] .preview .play').click(timeout=15_000)
    page.wait_for_function("SRC.pitch && !SRC.pitch.audio.paused", timeout=10_000)
    audio_paused = page.evaluate_handle("SRC.pitch.audio")
    page.click('[data-drop="pitch"] .file [data-remove]')
    assert page.evaluate("a => a.paused", audio_paused) is True
    assert page.evaluate("SRC.pitch === undefined")


def test_join_reorder_and_join(page, app_url, fixtures):
    goto(page, app_url, "join")
    drop(page, "join", fixtures["tone_wav"], fixtures["mono_flac"])
    items = page.locator("#joinList .fitem")
    expect(items).to_have_count(2)
    expect(page.locator("#joinGo")).to_be_enabled(timeout=20_000)
    first = items.nth(0).locator(".meta b").inner_text()
    page.click('#joinList [data-dn="0"]')
    assert items.nth(1).locator(".meta b").inner_text() == first
    page.click("#joinGo")
    expect(page.locator("#joinProg")).to_have_class(re.compile(r"\bdone\b"), timeout=60_000)
    expect(page.locator("#joinRes")).to_contain_text("joined.mp3")


def test_convert_to_ogg(page, app_url, fixtures):
    """Regression: OGG used to crash the server."""
    goto(page, app_url, "convert")
    drop(page, "convert", fixtures["video_mp4"])
    page.click('#convFmt button[data-v="ogg"]')
    page.click("#convertGo")
    expect(page.locator("#convertRes")).to_contain_text(".ogg", timeout=60_000)


def test_split_options_and_estimate(page, app_url, fixtures):
    goto(page, app_url, "split")
    expect(page.locator("#stemsField")).to_be_hidden()
    page.click('#engine .opt[data-v="demucs"]')
    expect(page.locator("#stemsField")).to_be_visible()
    page.click('#engine .opt[data-v="bs_roformer"]')
    expect(page.locator("#stemsField")).to_be_hidden()
    drop(page, "split", fixtures["tone_wav"])
    expect(page.locator("#estimate")).to_contain_text("≈")
    expect(page.locator("#splitGo")).to_be_enabled()


@pytest.mark.parametrize("w,h", [(375, 812), (768, 1024), (1440, 900)])
def test_responsive_no_horizontal_scroll(page, app_url, w, h):
    page.set_viewport_size({"width": w, "height": h})
    page.goto(app_url)
    for name in PAGES:
        page.click(f'nav button[data-page="{name}"]')
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert over <= 1, f"{name} overflows horizontally by {over}px at {w}px"


def test_every_control_has_an_accessible_name(page, app_url, fixtures):
    page.goto(app_url)
    missing = page.evaluate("""() => [...document.querySelectorAll('button, input:not([type=file]), select, a[href]')]
      .filter(el => !(el.getAttribute('aria-label') || el.title || el.textContent.trim() ||
                      (el.labels && el.labels.length) || el.getAttribute('aria-labelledby')))
      .map(el => el.outerHTML.slice(0, 90))""")
    assert not missing, missing


def test_keyboard_opens_file_picker(page, app_url):
    page.goto(app_url)
    page.focus('[data-drop="split"] .drop')
    with page.expect_file_chooser(timeout=5000):
        page.keyboard.press("Enter")


def test_removing_file_deletes_upload(page, app_url, fixtures):
    goto(page, app_url, "convert")
    drop(page, "convert", fixtures["tone_mp3"])
    expect(page.locator("#convertGo")).to_be_enabled()
    with page.expect_request(lambda r: r.method == "DELETE" and "/api/uploads/" in r.url):
        page.click('[data-drop="convert"] .file [data-remove]')


def test_images_and_lang(page, app_url):
    page.goto(app_url)
    assert page.evaluate("document.documentElement.lang") == "en"
    assert page.evaluate("document.querySelectorAll('img:not([alt])').length") == 0
