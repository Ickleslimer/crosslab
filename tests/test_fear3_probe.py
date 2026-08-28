from pathlib import Path


PROBE = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_steam_probe.js"
)


def test_run18_filter_is_exact_and_gameplay_gated() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "trigger: [0x64, 0x01, 0x00, 0x00, 0x00]" in source
    assert "this.channel === 4098 && messageSize > 0" in source
    assert "this.channel === 4101 && messageSize === run18Filter.trigger.length" in source
    assert "matchesBytes(candidate, run18Filter.trigger)" in source
    assert "retval.replace(0)" in source

