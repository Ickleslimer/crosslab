import hashlib
from pathlib import Path

PROBE_RUN22 = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_run22_probe.js"
)


def test_run22_is_entry_only_and_stalker_free() -> None:
    source = PROBE_RUN22.read_text(encoding="utf-8")

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


def test_run22_preflight_is_pinned_to_reviewed_images_and_entry_bytes() -> None:
    source = PROBE_RUN22.read_text(encoding="utf-8")

    assert "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915" in source
    assert "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7" in source
    assert "peTimestamp: 0x4e0d0b76" in source
    assert "sizeOfImage: 0x15e2000" in source
    assert "peTimestamp: 0x6a70ef0e" in source
    assert "sizeOfImage: 0x1498000" in source
    assert "closeChannelRva: 0x611960" in source
    assert "0x55, 0x8b, 0xec, 0x8b, 0x49, 0x04, 0xff, 0x75" in source
    assert "bytesMatch(closeChannelTarget, run22ReviewedManifest.steamclient.closeChannelEntryBytes)" in source
    assert "RUN22 PREFLIGHT ABORT" in source


def test_run22_hooks_target_vtable_slot_5_with_fail_closed_rollback() -> None:
    source = PROBE_RUN22.read_text(encoding="utf-8")

    assert "legacyNetworkingVtable.add(5 * Process.pointerSize).readPointer()" in source
    assert "legacyNetworkingVtable.add(4 * Process.pointerSize).readPointer()" not in source
    assert "requiredAttach" in source
    assert "cleanupRun22" in source
    assert "run22InstalledListeners.pop()" in source


def test_run22_captures_immediate_return_address_and_bounded_backtrace_with_synchronous_latch() -> None:
    source = PROBE_RUN22.read_text(encoding="utf-8")

    assert "if (run22Finished || run22Captured) {\n            return;\n        }\n        const retAddr = this.returnAddress;\n        const channel = args[2].toInt32();" in source
    assert "if (channel !== 4101) {\n            return;\n        }" in source
    assert "if (run22Captured) {\n            return;\n        }\n        run22Captured = true;" in source
    assert "Process.findModuleByAddress(retAddr)" in source
    assert "retAddr.sub(owner.base)" in source
    assert "Thread.backtrace(context, Backtracer.ACCURATE)" in source
    assert "frames.slice(0, limit)" in source
    assert "Run22CloseP2PChannelEvidence" in source


def test_run22_timer_initialized_before_hook_installation() -> None:
    source = PROBE_RUN22.read_text(encoding="utf-8")

    timer_pos = source.find("timeoutGuard = setTimeout")
    attach_pos = source.find("requiredAttach(closeChannelTarget")
    assert timer_pos != -1
    assert attach_pos != -1
    assert timer_pos < attach_pos, "Timeout guard must be armed before installing the live hook"
    assert "clearTimeout(timeoutGuard)" in source
    assert "timeoutGuard = null" in source
    assert 'cleanupRun22("control channel 4101 captured")' in source
    assert "180000" in source


def test_run22_probe_hashes_match_reviewed_candidate() -> None:
    canonical = PROBE_RUN22.read_text(encoding="utf-8").encode("utf-8")
    git_blob = hashlib.sha1(
        b"blob " + str(len(canonical)).encode("ascii") + b"\0" + canonical
    ).hexdigest()
    sha256 = hashlib.sha256(canonical).hexdigest()

    assert git_blob == "b3865b142040b10252aec381a71e234210e54818"
    assert sha256 == "4addf0b431b54f0df1bedc7a88eeda6fcafdd397483e467cb88b58e84e6373e0"