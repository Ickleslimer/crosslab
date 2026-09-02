import hashlib
from pathlib import Path

PROBE_RUN24 = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_run24_probe.js"
)


def test_run24_is_entry_only_and_stalker_free() -> None:
    source = PROBE_RUN24.read_text(encoding="utf-8")

    assert "Stalker.follow" not in source
    assert "iterator.putCallout" not in source
    assert "iterator.keep" not in source
    assert "fear3_close_call_924084" not in source
    assert "fear3_breadcrumb_indirect_0187f9" not in source
    assert "fear3_breadcrumb_relative_0b12bd" not in source
    assert "fear3_breadcrumb_relative_448653" not in source
    assert "retval.replace(" not in source
    assert "CloseP2PSessionWithUser" not in source
    assert "reduce instrumentation risk" in source


def test_run24_preflight_is_pinned_to_reviewed_images_and_entry_bytes() -> None:
    source = PROBE_RUN24.read_text(encoding="utf-8")

    assert "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915" in source
    assert "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7" in source
    assert "peTimestamp: 0x4e0d0b76" in source
    assert "sizeOfImage: 0x15e2000" in source
    assert "peTimestamp: 0x6a70ef0e" in source
    assert "sizeOfImage: 0x1498000" in source
    assert "peerSteamCloseRva: 0x923f90" in source
    assert "0x83, 0xec, 0x08, 0x55, 0x8b, 0x6c, 0x24, 0x10" in source
    assert "bytesMatch(peerSteamCloseTarget, run24ReviewedManifest.fear3.peerSteamCloseEntryBytes)" in source
    assert "RUN24 PREFLIGHT ABORT" in source


def test_run24_hooks_target_peer_steam_entry_with_fail_closed_rollback() -> None:
    source = PROBE_RUN24.read_text(encoding="utf-8")

    assert "run24MainModule.base.add(run24ReviewedManifest.fear3.peerSteamCloseRva)" in source
    assert "requiredAttach" in source
    assert "cleanupRun24" in source
    assert "run24InstalledListeners.pop()" in source


def test_run24_captures_immediate_return_address_descriptor_and_bounded_backtrace_with_synchronous_latch() -> None:
    source = PROBE_RUN24.read_text(encoding="utf-8")

    assert "if (run24Finished || run24Captured) {\n            return;\n        }\n        const retAddr = this.returnAddress;\n        const peerSteamThis = this.context.ecx;" in source
    assert "if (channel !== 4101) {\n            return;\n        }" in source
    assert "if (run24Captured) {\n            return;\n        }\n        run24Captured = true;" in source
    assert "endpointDescriptorPtr" in source
    assert "descriptor_fields" in source
    assert "Process.findModuleByAddress(retAddr)" in source
    assert "retAddr.sub(owner.base)" in source
    assert "Thread.backtrace(context, Backtracer.ACCURATE)" in source
    assert "frames.slice(0, limit)" in source
    assert "Run24PeerSteamCloseEvidence" in source


def test_run24_timer_initialized_before_hook_installation() -> None:
    source = PROBE_RUN24.read_text(encoding="utf-8")

    timer_pos = source.find("timeoutGuard = setTimeout")
    attach_pos = source.find("requiredAttach(peerSteamCloseTarget")
    assert timer_pos != -1
    assert attach_pos != -1
    assert timer_pos < attach_pos, "Timeout guard must be armed before installing the live hook"
    assert "clearTimeout(timeoutGuard)" in source
    assert "timeoutGuard = null" in source
    assert 'cleanupRun24("PeerSteam::CloseChannel(4101) captured")' in source
    assert "600000" in source


def test_run24_probe_hashes_match_reviewed_candidate() -> None:
    canonical = PROBE_RUN24.read_text(encoding="utf-8").encode("utf-8")
    git_blob = hashlib.sha1(
        b"blob " + str(len(canonical)).encode("ascii") + b"\0" + canonical
    ).hexdigest()
    sha256 = hashlib.sha256(canonical).hexdigest()

    assert git_blob == "2644cb69fff6f4d59d9513096e32f9c7ab4fffca"
    assert sha256 == "9c3157db6181a8f902b7f0e1fbe240ba41256cf29bb7dc2ca0be26acd6a3574c"