"""Main user journey on the real GPU: upload a song, watch live progress, use the mixer."""
import re
import sys
from pathlib import Path

import pytest
import soundfile as sf
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "benchmarks"))
import metrics as M  # noqa: E402

pytestmark = [pytest.mark.e2e, pytest.mark.gpu, pytest.mark.slow]


@pytest.fixture(scope="module")
def song(tmp_root):
    tracks = M.musdb_tracks(n=1)
    if not tracks:
        pytest.skip("MUSDB18 test data not downloaded")
    p = tmp_root / "e2e song.wav"
    sf.write(p, M.load_track(tracks[0])["mixture"].T, M.SR)
    return p


def test_split_with_live_progress_and_mixer(page, gpu_app_url, song, errors):
    page.goto(gpu_app_url)
    expect(page.locator("#devsub")).to_have_text("GPU acceleration on")
    page.set_input_files('[data-drop="split"] input[type=file]', str(song))
    expect(page.locator("#splitGo")).to_be_enabled()
    page.click('#speed button[data-v="balanced"]')
    page.click("#splitGo")

    seen = set()
    prog = page.locator("#splitProg")
    for _ in range(1200):  # up to ~10 min incl. first-time model load
        txt = prog.locator(".pg-pct").inner_text().replace("%", "").strip()
        if txt.isdigit():
            seen.add(int(txt))
        if "done" in (prog.get_attribute("class") or "") or "err" in (prog.get_attribute("class") or ""):
            break
        page.wait_for_timeout(500)
    expect(prog).to_have_class(re.compile(r"\bdone\b"))
    mid = sorted(v for v in seen if 10 < v < 92)
    assert len(mid) >= 3, f"progress should visibly climb during extraction, saw {sorted(seen)}"
    expect(prog.locator(".eta")).to_contain_text("Finished in")

    rows = page.locator("#splitRes .stem")
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text("Vocals")
    expect(rows.nth(1)).to_contain_text("Instrumental")
    rows.nth(0).locator(".ms.m").click()
    expect(rows.nth(0)).to_have_class(re.compile(r"\bmuted\b"))
    page.click("#splitRes [data-play]")
    page.wait_for_timeout(1500)
    t = page.locator("#splitRes .time").inner_text()
    assert not t.startswith("0:00 /"), f"synced playback did not advance: {t}"
    page.click("#splitRes [data-play]")
    with page.expect_download(timeout=60_000) as dl:
        page.click("#splitRes [data-export]")
    assert dl.value.suggested_filename.startswith("custom mix")
    assert not errors
