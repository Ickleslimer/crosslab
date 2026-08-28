from pathlib import Path


PROBE = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_steam_probe.js"
)


def test_run19_filter_is_exact_and_gameplay_gated() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "0x50, 0x00, 0x61, 0x64, 0x80, 0x24, 0x01, 0x00" in source
    assert "0x05, 0x00, 0x00, 0x80, 0x80, 0x00, 0x00, 0x00" in source
    assert "this.channel === 4098 && messageSize > 0" in source
    assert "this.channel === 4101 && messageSize === run19Filter.trigger.length" in source
    assert "matchesBytes(candidate, run19Filter.trigger)" in source
    assert "retval.replace(0)" in source


def test_run19_filter_does_not_match_neighboring_control_frames() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "trigger: [0x64, 0x01, 0x00, 0x00, 0x00]" not in source
    assert "Run19Filter DROPPED" in source
    assert "(16 bytes, channel=4101)" in source
