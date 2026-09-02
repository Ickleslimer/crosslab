/**
 * FEAR 3 Steam P2P Diagnostic Probe - Run 25 (Despair::Net::LobbyPeer::DisconnectChannel Entry Evidence)
 * 
 * Strict entry-only Interceptor instrumentation targeting Despair::Net::LobbyPeer::DisconnectChannel at F.E.A.R. 3.exe+0x38ed80.
 * Completely eliminates Stalker and mid-function hooks to reduce instrumentation risk.
 * 600-second safety timeout for relaxed lobby reproduction.
 * Line endings: Pinned to LF via repository .gitattributes.
 * 
 * Usage:
 *   frida -n "F.E.A.R. 3.exe" -l fear3_run25_probe.js
 */

console.log("[CrossLab Probe] Initializing Run 25 entry-only diagnostic probe in F.E.A.R. 3...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (!steamApi) {
    console.log("[CrossLab Probe] RUN25 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded");
    throw new Error("RUN25 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded");
}

const run25ReviewedManifest = {
    fear3: {
        moduleName: "F.E.A.R. 3.exe",
        sha256: "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915",
        peTimestamp: 0x4e0d0b76,
        sizeOfImage: 0x15e2000,
        lobbyPeerDisconnectRva: 0x38ed80,
        lobbyPeerDisconnectEntryBytes: [
            0x83, 0xec, 0x08, 0x56, 0x8b, 0xf1, 0x8b, 0x4c,
            0x24, 0x10, 0x8b, 0x01, 0x85, 0xc0, 0x75, 0x23
        ]
    },
    steamclient: {
        moduleName: "steamclient.dll",
        sha256: "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7",
        peTimestamp: 0x6a70ef0e,
        sizeOfImage: 0x1498000
    }
};

const bytesMatch = function(address, expected) {
    try {
        const actual = new Uint8Array(address.readByteArray(expected.length));
        for (let index = 0; index < expected.length; index++) {
            if (actual[index] !== expected[index]) {
                return false;
            }
        }
        return true;
    } catch (_) {
        return false;
    }
};

const peIdentity = function(module) {
    const peOffset = module.base.add(0x3c).readU32();
    const ntHeaders = module.base.add(peOffset);
    if (ntHeaders.readU32() !== 0x00004550) {
        throw new Error(`${module.name} has no PE signature`);
    }
    return {
        peTimestamp: ntHeaders.add(8).readU32(),
        sizeOfImage: ntHeaders.add(0x50).readU32()
    };
};

const fileSha256 = function(path) {
    if (typeof File === "undefined" ||
        typeof File.readAllBytes !== "function" ||
        typeof Checksum === "undefined" ||
        typeof Checksum.compute !== "function") {
        throw new Error("Frida File.readAllBytes/Checksum.compute unavailable");
    }
    return Checksum.compute("sha256", File.readAllBytes(path)).toLowerCase();
};

const validateReviewedImage = function(module, expected) {
    if (!module) {
        throw new Error(`required module ${expected.moduleName} is not loaded`);
    }
    const identity = peIdentity(module);
    const sha256 = fileSha256(module.path);
    const mismatches = [];
    if (module.name.toLowerCase() !== expected.moduleName.toLowerCase()) {
        mismatches.push(`name=${module.name}`);
    }
    if (sha256 !== expected.sha256) {
        mismatches.push(`sha256=${sha256}`);
    }
    if (identity.peTimestamp !== expected.peTimestamp) {
        mismatches.push(`pe_timestamp=0x${identity.peTimestamp.toString(16)}`);
    }
    if (identity.sizeOfImage !== expected.sizeOfImage || module.size !== expected.sizeOfImage) {
        mismatches.push(`size_of_image=0x${identity.sizeOfImage.toString(16)} module_size=0x${module.size.toString(16)}`);
    }
    if (mismatches.length > 0) {
        throw new Error(`${expected.moduleName} manifest mismatch: ${mismatches.join(" ")}`);
    }
    console.log(`[CrossLab Probe] Run25 manifest OK ${module.name} sha256=${sha256} pe_timestamp=0x${identity.peTimestamp.toString(16)} size_of_image=0x${identity.sizeOfImage.toString(16)}`);
};

const run25MainModule = Process.mainModule;
const run25SteamClient = Process.findModuleByName("steamclient.dll");
try {
    if (!run25MainModule) {
        throw new Error("required main module is not available");
    }
    validateReviewedImage(run25MainModule, run25ReviewedManifest.fear3);
    validateReviewedImage(run25SteamClient, run25ReviewedManifest.steamclient);
    console.log("[CrossLab Probe] Run25 preflight manifest OK; stalker-free entry-only mode active");
} catch (error) {
    console.log(`[CrossLab Probe] RUN25 PREFLIGHT ABORT: ${error}`);
    throw error;
}

const run25InstalledListeners = [];
let run25Finished = false;
let run25Captured = false;
let timeoutGuard = null;

const cleanupRun25 = function(reason) {
    if (run25Finished) {
        return;
    }
    run25Finished = true;
    if (timeoutGuard !== null) {
        clearTimeout(timeoutGuard);
        timeoutGuard = null;
    }
    while (run25InstalledListeners.length > 0) {
        const listener = run25InstalledListeners.pop();
        try {
            listener.detach();
        } catch (_) {}
    }
    console.log(`[CrossLab Probe] Run25 detached all hooks (reason: ${reason})`);
};

const requiredAttach = function(address, label, callbacks) {
    if (!address || address.isNull()) {
        cleanupRun25(`cannot resolve ${label}`);
        throw new Error(`RUN25 PREFLIGHT ABORT: cannot resolve ${label}`);
    }
    try {
        const listener = Interceptor.attach(address, callbacks);
        run25InstalledListeners.push(listener);
        console.log(`  [+] Attached ${label} at ${address}`);
        return listener;
    } catch (error) {
        cleanupRun25(`required hook failed: ${label}`);
        throw new Error(`RUN25 PREFLIGHT ABORT: required hook failed: ${label}: ${error}`);
    }
};

const stackFrame = function(address) {
    const rawAddress = address.toString();
    try {
        const owner = Process.findModuleByAddress(address);
        if (!owner) {
            return `${rawAddress} <no-module>`;
        }
        return `${rawAddress} ${owner.name}+0x${address.sub(owner.base).toString(16)}`;
    } catch (error) {
        return `${rawAddress} <frame unavailable: ${error}>`;
    }
};

const stackTrace = function(context, maxFrames) {
    const limit = maxFrames || 12;
    try {
        const frames = Thread.backtrace(context, Backtracer.ACCURATE);
        return frames.slice(0, limit).map(stackFrame);
    } catch (error) {
        return [`<stack unavailable: ${error}>`];
    }
};

// Preflight target function entry: Despair::Net::LobbyPeer::DisconnectChannel (RVA +0x38ed80)
const lobbyPeerDisconnectTarget = run25MainModule.base.add(run25ReviewedManifest.fear3.lobbyPeerDisconnectRva);
if (!bytesMatch(lobbyPeerDisconnectTarget, run25ReviewedManifest.fear3.lobbyPeerDisconnectEntryBytes)) {
    throw new Error(`RUN25 PREFLIGHT ABORT: Despair::Net::LobbyPeer::DisconnectChannel entry byte signature mismatch at F.E.A.R. 3.exe+0x${run25ReviewedManifest.fear3.lobbyPeerDisconnectRva.toString(16)}`);
}
console.log(`[CrossLab Probe] Run25 live target preflight OK target=${lobbyPeerDisconnectTarget} authority=F.E.A.R. 3.exe+0x${run25ReviewedManifest.fear3.lobbyPeerDisconnectRva.toString(16)} entry_bytes=OK`);

// Arm the 600s Safety Timeout Guard BEFORE hook installation
timeoutGuard = setTimeout(function() {
    cleanupRun25("600s safety timeout reached");
}, 600000);

// Primary Run 25 Hook: Despair::Net::LobbyPeer::DisconnectChannel (RVA +0x38ed80)
requiredAttach(lobbyPeerDisconnectTarget, "Run25 Despair::Net::LobbyPeer::DisconnectChannel entry target", {
    onEnter: function(args) {
        if (run25Finished || run25Captured) {
            return;
        }
        const retAddr = this.returnAddress;
        const lobbyPeerThis = this.context.ecx;
        const endpointDescriptorPtr = args[0];

        // Synchronous latch: claim one-shot capture immediately before any async or stack work
        if (run25Captured) {
            return;
        }
        run25Captured = true;

        const nowMs = Date.now();
        const tid = Process.getCurrentThreadId();
        let retModule = "<no-module>";
        let retRva = "0x0";
        const owner = Process.findModuleByAddress(retAddr);
        if (owner) {
            retModule = owner.name;
            retRva = `0x${retAddr.sub(owner.base).toString(16)}`;
        }

        let listenerPtr = "0x0";
        let channelOffset = 0;
        try {
            if (!lobbyPeerThis.isNull()) {
                listenerPtr = lobbyPeerThis.add(0x70).readPointer().toString();
                channelOffset = lobbyPeerThis.add(0x74).readU16();
            }
        } catch (_) {}

        let descriptorReadOk = false;
        let descriptorReadError = null;
        let descriptorDword0 = 0;
        let descriptorWord4 = 0;
        let descriptorWord6 = 0;
        try {
            if (!endpointDescriptorPtr || endpointDescriptorPtr.isNull()) {
                descriptorReadError = "endpoint descriptor pointer is NULL";
            } else {
                descriptorDword0 = endpointDescriptorPtr.readU32();
                descriptorWord4 = endpointDescriptorPtr.add(4).readU16();
                descriptorWord6 = endpointDescriptorPtr.add(6).readU16();
                descriptorReadOk = true;
            }
        } catch (error) {
            descriptorReadError = error ? error.toString() : "unknown read error";
        }

        const evidence = {
            event: "Run25LobbyPeerDisconnectEvidence",
            timestamp: new Date(nowMs).toISOString(),
            tid: tid,
            lobby_peer_this: lobbyPeerThis.toString(),
            listener_ptr: listenerPtr,
            channel_offset: channelOffset,
            endpoint_descriptor_ptr: endpointDescriptorPtr ? endpointDescriptorPtr.toString() : "0x0",
            descriptor_read_ok: descriptorReadOk,
            descriptor_read_error: descriptorReadError,
            input_descriptor_fields: {
                dword0: `0x${descriptorDword0.toString(16).padStart(8, "0")}`,
                word4: `0x${descriptorWord4.toString(16).padStart(4, "0")}`,
                word6: `0x${descriptorWord6.toString(16).padStart(4, "0")}`
            },
            return_address: {
                raw: retAddr.toString(),
                module: retModule,
                rva: retRva
            },
            backtrace: stackTrace(this.context, 12)
        };

        console.log(`[Client Probe] ${JSON.stringify(evidence)}`);
        console.log("[Client Probe] Despair::Net::LobbyPeer::DisconnectChannel entry detected. Detaching Run 25 probe.");

        setImmediate(function() {
            cleanupRun25("LobbyPeer::DisconnectChannel captured");
        });
    }
});

console.log("[CrossLab Probe] Run 25 probe attached successfully. Waiting for LobbyPeer::DisconnectChannel event...");