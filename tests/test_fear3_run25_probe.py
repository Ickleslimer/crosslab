import hashlib
from pathlib import Path

PROBE_RUN25 = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_run25_probe.js"
)


def test_run25_is_entry_only_and_stalker_free() -> None:
    source = PROBE_RUN25.read_text(encoding="utf-8")

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


def test_run25_preflight_is_pinned_to_reviewed_images_and_entry_bytes() -> None:
    source = PROBE_RUN25.read_text(encoding="utf-8")

    assert "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915" in source
    assert "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7" in source
    assert "peTimestamp: 0x4e0d0b76" in source
    assert "sizeOfImage: 0x15e2000" in source
    assert "peTimestamp: 0x6a70ef0e" in source
    assert "sizeOfImage: 0x1498000" in source
    assert "lobbyPeerDisconnectRva: 0x38ed80" in source
    assert "0x83, 0xec, 0x08, 0x56, 0x8b, 0xf1, 0x8b, 0x4c" in source
    assert "bytesMatch(lobbyPeerDisconnectTarget, run25ReviewedManifest.fear3.lobbyPeerDisconnectEntryBytes)" in source
    assert "RUN25 PREFLIGHT ABORT" in source


def test_run25_hooks_target_lobby_peer_entry_with_fail_closed_rollback() -> None:
    source = PROBE_RUN25.read_text(encoding="utf-8")

    assert "run25MainModule.base.add(run25ReviewedManifest.fear3.lobbyPeerDisconnectRva)" in source
    assert "requiredAttach" in source
    assert "cleanupRun25" in source
    assert "run25InstalledListeners.pop()" in source


def test_run25_captures_immediate_args_and_explicit_read_status_telemetry() -> None:
    source = PROBE_RUN25.read_text(encoding="utf-8")

    # Immediate capture of returnAddress, ecx, and args[0] before other operations
    assert "if (run25Finished || run25Captured) {\n            return;\n        }\n        const retAddr = this.returnAddress;\n        const lobbyPeerThis = this.context.ecx;\n        const endpointDescriptorPtr = args[0];" in source
    assert "if (run25Captured) {\n            return;\n        }\n        run25Captured = true;" in source
    assert "listener_ptr: listenerPtr" in source
    assert "channel_offset: channelOffset" in source
    assert "descriptor_read_ok: descriptorReadOk" in source
    assert "descriptor_read_error: descriptorReadError" in source
    assert "input_descriptor_fields" in source
    assert "Process.findModuleByAddress(retAddr)" in source
    assert "retAddr.sub(owner.base)" in source
    assert "Thread.backtrace(context, Backtracer.ACCURATE)" in source
    assert "frames.slice(0, limit)" in source
    assert "Run25LobbyPeerDisconnectEvidence" in source


def test_run25_timer_initialized_before_hook_installation() -> None:
    source = PROBE_RUN25.read_text(encoding="utf-8")

    timer_pos = source.find("timeoutGuard = setTimeout")
    attach_pos = source.find("requiredAttach(lobbyPeerDisconnectTarget")
    assert timer_pos != -1
    assert attach_pos != -1
    assert timer_pos < attach_pos, "Timeout guard must be armed before installing the live hook"
    assert "clearTimeout(timeoutGuard)" in source
    assert "timeoutGuard = null" in source
    assert 'cleanupRun25("LobbyPeer::DisconnectChannel captured")' in source
    assert "600000" in source


def test_run25_probe_hashes_match_reviewed_candidate() -> None:
    raw_bytes = PROBE_RUN25.read_bytes()
    assert b"\r" not in raw_bytes, "Probe file on disk must be pure LF under .gitattributes"
    git_blob = hashlib.sha1(
        b"blob " + str(len(raw_bytes)).encode("ascii") + b"\0" + raw_bytes
    ).hexdigest()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    assert git_blob == "c35fcf44f4a40659cc652488e4e50e89770f204d"
    assert sha256 == "790e5fadd38cd117caa4aa40acefac10835b3644e3d73f858dd3b2818c493a93"