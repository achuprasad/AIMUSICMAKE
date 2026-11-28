"""Browser end-to-end tests (Playwright). Run with --browser chromium --browser firefox."""
import re

import numpy as np
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

PAGES = {"split": "Vocal Remover & Stem Splitter", "pitch": "Pitch & Tempo Changer", "analyze": "Key & BPM Finder",
         "cut": "Audio Cutter", "join": "Audio Joiner", "convert": "Audio Converter", "support": "Help & Feedback",
         "voice": "Malayalam Voice Studio"}


def goto(page, url, name):
    page.goto(url)
    page.click(f'nav button[data-page="{name}"]')
    expect(page.locator(f"#page-{name} h1")).to_have_text(PAGES[name])


def drop(page, name, *files):
    page.set_input_files(f'[data-drop="{name}"] input[type=file]', [str(f) for f in files])


def test_loads_and_navigates(page, app_url, errors):
    page.goto(app_url)
    expect(page).to_have_title("Mixlumo — AI Vocal Remover & Music Editor")
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


# ------------------------------------------------------------------ Help & Feedback
def test_feedback_submit_and_list(page, app_url, errors):
    goto(page, app_url, "support")
    page.click('#fbType button[data-v="bug"]')
    page.select_option("#fbTool", "split")
    page.fill("#fbTitle", "Stems are too quiet")
    page.fill("#fbMsg", "After splitting, the vocal stem is very quiet compared to the original.")
    page.click('#fbStars button[data-v="4"]')
    expect(page.locator("#fbStars button.on")).to_have_count(4)
    page.click("#fbSend")
    res = page.locator("#fbResult")
    expect(res).to_contain_text("Thank you!")
    expect(res).to_contain_text("saved on this computer")  # tests run with e-mail off: the page says so honestly
    ref = res.locator("code").inner_text()
    assert ref.startswith("FB-")
    gh = res.locator("#fbGithub").get_attribute("href")
    assert gh.startswith("https://github.com/achuprasad/AIMUSICMAKE/issues/new?") and "template=bug_report.yml" in gh
    assert "Stems+are+too+quiet" in gh
    expect(page.locator("#fbMine .sub")).to_have_count(1)
    expect(page.locator("#fbMine")).to_contain_text(ref)
    expect(page.locator("#fbTitle")).to_have_value("")
    assert not errors


def test_feedback_validation_messages(page, app_url):
    goto(page, app_url, "support")
    page.fill("#fbTitle", "Hi there")
    page.fill("#fbMsg", "short")
    page.click("#fbSend")
    expect(page.locator("#fbResult")).to_contain_text("at least 10 characters")
    page.fill("#fbMsg", "A long enough description of the idea.")
    page.fill("#fbEmail", "me@example.com")
    page.click("#fbSend")
    expect(page.locator("#fbResult")).to_contain_text("consent")
    expect(page.locator("#fbMine .sub")).to_have_count(0)


def test_feedback_xss_is_rendered_as_text(page, app_url, errors):
    goto(page, app_url, "support")
    evil_title = '<img src=x onerror="window.__xss=1">'
    evil_msg = '<script>window.__xss=2</script><b onmouseover="window.__xss=3">bold?</b> hello world'
    page.fill("#fbTitle", evil_title)
    page.fill("#fbMsg", evil_msg)
    page.click("#fbSend")
    expect(page.locator("#fbMine .sub")).to_have_count(1)
    page.wait_for_timeout(500)
    assert page.evaluate("window.__xss") is None
    assert page.locator("#fbMine img, #fbMine script, #fbMine .sub p b").count() == 0
    expect(page.locator("#fbMine .sub b").first).to_have_text(evil_title)  # shown literally
    assert not errors


def test_roadmap_voting(page, app_url):
    goto(page, app_url, "support")
    items = page.locator("#roadmap .rm")
    expect(items).to_have_count(10)
    btn = page.locator('#roadmap .vote[data-id="noise-removal"]')
    before = int(btn.locator("b").inner_text())
    btn.click()
    expect(btn).to_have_class(re.compile(r"\bon\b"))
    expect(btn).to_have_attribute("aria-pressed", "true")
    expect(btn.locator("b")).to_have_text(str(before + 1))
    page.reload()
    goto(page, app_url, "support")
    btn = page.locator('#roadmap .vote[data-id="noise-removal"]')
    expect(btn).to_have_class(re.compile(r"\bon\b"))  # remembered for this browser
    btn.click()
    expect(btn.locator("b")).to_have_text(str(before))


def test_faq_opens(page, app_url):
    goto(page, app_url, "support")
    faq = page.locator("details.faq").first
    expect(faq.locator("div")).to_be_hidden()
    faq.locator("summary").click()
    expect(faq.locator("div")).to_be_visible()


def test_honeypot_is_invisible_to_people(page, app_url):
    goto(page, app_url, "support")
    box = page.locator("#fbWebsite").bounding_box()
    assert box is None or box["x"] < -1000 or box["width"] <= 1


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


def test_effect_controls_disabled_until_switched_on(page, app_url):
    goto(page, app_url, "pitch")
    expect(page.locator("#lofiAmt")).to_be_disabled()
    for s in ("#echoDelay", "#echoFb", "#echoMix"):
        expect(page.locator(s)).to_be_disabled()
    page.check("#lofiOn")
    expect(page.locator("#lofiAmt")).to_be_enabled()
    expect(page.locator("#echoDelay")).to_be_disabled()
    page.check("#echoOn")
    for s in ("#echoDelay", "#echoFb", "#echoMix"):
        expect(page.locator(s)).to_be_enabled()
    page.locator("#echoDelay").fill("500")
    expect(page.locator("#echoDelayVal")).to_have_text("500 ms")
    page.locator("#lofiAmt").fill("80")
    expect(page.locator("#lofiVal")).to_have_text("80")


def test_effect_presets(page, app_url, errors):
    goto(page, app_url, "pitch")
    page.click('#fxPresets button[data-v="slowed"]')
    expect(page.locator("#tp")).to_have_value("80")
    expect(page.locator("#tpVal")).to_have_text("0.80×")
    expect(page.locator("#keepPitch")).not_to_be_checked()
    expect(page.locator("#echoOn")).to_be_checked()
    expect(page.locator("#lofiOn")).not_to_be_checked()
    expect(page.locator("#echoDelayVal")).to_have_text("450 ms")
    expect(page.locator("#echoFbVal")).to_have_text("40%")
    expect(page.locator("#echoMixVal")).to_have_text("35%")
    page.click('#fxPresets button[data-v="chill"]')
    expect(page.locator("#lofiOn")).to_be_checked()
    expect(page.locator("#lofiVal")).to_have_text("55")
    expect(page.locator("#tp")).to_have_value("85")
    page.click('#fxPresets button[data-v="reset"]')
    expect(page.locator("#tp")).to_have_value("100")
    expect(page.locator("#keepPitch")).to_be_checked()
    expect(page.locator("#lofiOn")).not_to_be_checked()
    expect(page.locator("#echoOn")).not_to_be_checked()
    assert not errors


def test_live_lofi_and_echo_preview(page, app_url, fixtures, errors):
    goto(page, app_url, "pitch")
    drop(page, "pitch", fixtures["tone_wav"])
    page.click('[data-drop="pitch"] .preview .play')
    page.wait_for_function("SRC.pitch && SRC.pitch.fx && !SRC.pitch.audio.paused", timeout=10_000)
    # both effects start switched off: no echo, no filtering, no noise
    fx = "SRC.pitch.fx.nodes"
    page.wait_for_function(f"{fx}.wet.gain.value < 0.001 && {fx}.lp.frequency.value > 19000")
    page.check("#echoOn")
    page.locator("#echoDelay").fill("250")
    page.wait_for_function(f"Math.abs({fx}.delay.delayTime.value - 0.25) < 0.005"
                           f" && Math.abs({fx}.wet.gain.value - 0.35) < 0.01")
    page.check("#lofiOn")
    page.wait_for_function(f"{fx}.lp.frequency.value < 7000 && {fx}.shaper.curve !== null && {fx}.ngain.gain.value > 0")
    # the echo path really carries sound
    rms = page.evaluate(f"""async () => {{
        const an = SRC.pitch.ctx.createAnalyser(); an.fftSize = 2048; {fx}.wet.connect(an);
        await new Promise(r => setTimeout(r, 700));
        const d = new Float32Array(an.fftSize); an.getFloatTimeDomainData(d);
        let s = 0; for (const v of d) s += v * v; return Math.sqrt(s / d.length);
    }}""")
    assert 0.005 < rms < 1.0, f"echo RMS {rms}"
    # switching off silences the effects again
    page.uncheck("#echoOn")
    page.uncheck("#lofiOn")
    page.wait_for_function(f"{fx}.wet.gain.value < 0.001 && {fx}.ngain.gain.value < 0.0005 && {fx}.shaper.curve === null")
    assert not errors


def _compare_module():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "scripts" / "compare_preview.py"
    spec = importlib.util.spec_from_file_location("compare_preview", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_live_preview_sounds_like_the_download(page, app_url, tmp_path, errors):
    """Lo-fi chill preset (tape speed + lo-fi + echo): the preview's real output and the downloaded file
    must match in pitch, speed, echo timing/level, tone colour, loudness and hiss (scripts/compare_preview.py)."""
    cmp = _compare_module()
    src = tmp_path / "preview test signal.wav"
    cmp.make_signal(src)
    goto(page, app_url, "pitch")
    page.set_input_files('[data-drop="pitch"] input[type=file]', str(src))
    page.click('[data-drop="pitch"] .preview .play', timeout=20_000)
    page.wait_for_function("SRC.pitch && SRC.pitch.fx && !SRC.pitch.audio.paused", timeout=10_000)
    params = cmp.apply_ui(page, {"preset": "chill"})
    xl, srl, xr, srr, name = cmp.capture_and_render(page, params)
    L, R = cmp.measure(xl, srl, params), cmp.measure(xr, srr, params)
    assert "lofi 55" in name and "echo 350ms" in name
    assert abs(1200 * np.log2(L["pitch_hz"] / R["pitch_hz"])) < 2, (L["pitch_hz"], R["pitch_hz"])
    assert abs(L["noise_onset_s"] - R["noise_onset_s"]) < 0.01
    assert len(L["echo_taps"]) == len(R["echo_taps"]) == 3
    for (tl, dl), (tr, dr) in zip(L["echo_taps"], R["echo_taps"], strict=True):
        assert abs(tl - tr) < 0.01 and abs(dl - dr) < 0.5, (L["echo_taps"], R["echo_taps"])
    for b, vl, vr in zip(cmp.BANDS[:-1], L["bands_db"][:-1], R["bands_db"][:-1], strict=True):  # 16 kHz: ~-30 dB
        assert abs(vl - vr) < 1.5, f"{b} Hz band: preview {vl:.1f} dB, download {vr:.1f} dB"
    assert abs(L["tone_rms_dbfs"] - R["tone_rms_dbfs"]) < 0.5
    assert abs(L["noise_rms_dbfs"] - R["noise_rms_dbfs"]) < 0.5
    assert abs(L["floor_dbfs"] - R["floor_dbfs"]) < 1.5
    assert abs(L["peak"] - R["peak"]) < 0.05 * R["peak"]
    assert not errors


def test_render_with_lofi_and_echo(page, app_url, fixtures, errors):
    goto(page, app_url, "pitch")
    drop(page, "pitch", fixtures["tone_wav"])
    page.check("#lofiOn")
    page.check("#echoOn")
    page.locator("#echoDelay").fill("200")
    page.click("#pitchGo")
    expect(page.locator("#pitchRes")).to_contain_text("lofi 60", timeout=60_000)
    expect(page.locator("#pitchRes")).to_contain_text("echo 200ms")
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
    # wait until the page script has wired the drop zone (CI runners can be slower than the keypress)
    page.wait_for_function("""document.querySelector('[data-drop="split"] .drop').onkeydown !== null""")
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
