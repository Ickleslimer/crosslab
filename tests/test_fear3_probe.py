from pathlib import Path


PROBE = (
    Path(__file__).parents[1]
    / "crosslab"
    / "cases"
    / "fear3"
    / "probes"
    / "fear3_steam_probe.js"
)


def test_run20_is_passive_and_gameplay_gated() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "Run 20 is observational" in source
    assert "this.channel === 4098 && messageSize > 0" in source
    assert "Run20Telemetry ACTIVE" in source
    assert "retval.replace(0)" not in source
    assert "DROPPED ReadP2PPacket" not in source


def test_run20_traces_auth_ticket_lifecycle_and_callback_results() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "GetAuthSessionTicket" in source
    assert "BeginAuthSession" in source
    assert "CancelAuthTicket" in source
    assert 'findExport("SteamAPI_RunCallbacks")' in source
    assert 'findExport("Steam_BGetCallback")' in source
    assert "LegacyCallbackDispatchNoTry" in source
    assert "LegacyCallbackDispatchTryCatch" in source
    assert "opcode signature mismatch" in source
    assert "ValidateAuthTicketResponse_t" in source
    assert "GetAuthSessionTicketResponse_t" in source
    assert "AuthTicketInvalidAlreadyUsed" in source


def test_run20_traces_relevant_dialog_paths() -> None:
    source = PROBE.read_text(encoding="utf-8")

    assert "DialogText api=" in source
    assert "DialogLiteralAccess" in source
    assert '"Failed authentication!"' in source
    assert '"Kicked by the host"' in source
    assert '"Connection lost"' in source
