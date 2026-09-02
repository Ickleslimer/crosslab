/**
 * FEAR 3 Steam P2P Diagnostic Probe - Run 24 (Despair::PeerSteam::CloseChannel Entry Caller Evidence)
 * 
 * Strict entry-only Interceptor instrumentation targeting Despair::PeerSteam::CloseChannel at F.E.A.R. 3.exe+0x923f90.
 * Completely eliminates Stalker and mid-function hooks to reduce instrumentation risk.
 * 600-second safety timeout for relaxed lobby reproduction.
 * Line endings: Pinned to LF via repository .gitattributes.
 * 
 * Usage:
 *   frida -n "F.E.A.R. 3.exe" -l fear3_run24_probe.js
 */

console.log("[CrossLab Probe] Initializing Run 24 entry-only diagnostic probe in F.E.A.R. 3...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (!steamApi) {
    console.log("[CrossLab Probe] RUN24 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded");
    throw new Error("RUN24 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded");
}

const run24ReviewedManifest = {
    fear3: {
        moduleName: "F.E.A.R. 3.exe",
        sha256: "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915",
        peTimestamp: 0x4e0d0b76,
        sizeOfImage: 0x15e2000,
        peerSteamCloseRva: 0x923f90,
        peerSteamCloseEntryBytes: [
            0x83, 0xec, 0x08, 0x55, 0x8b, 0x6c, 0x24, 0x10,
            0x57, 0x8b, 0xf9, 0x68, 0xec, 0x4e, 0x7f, 0x01
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
    console.log(`[CrossLab Probe] Run24 manifest OK ${module.name} sha256=${sha256} pe_timestamp=0x${identity.peTimestamp.toString(16)} size_of_image=0x${identity.sizeOfImage.toString(16)}`);
};

const run24MainModule = Process.mainModule;
const run24SteamClient = Process.findModuleByName("steamclient.dll");
try {
    if (!run24MainModule) {
        throw new Error("required main module is not available");
    }
    validateReviewedImage(run24MainModule, run24ReviewedManifest.fear3);
    validateReviewedImage(run24SteamClient, run24ReviewedManifest.steamclient);
    console.log("[CrossLab Probe] Run24 preflight manifest OK; stalker-free entry-only mode active");
} catch (error) {
    console.log(`[CrossLab Probe] RUN24 PREFLIGHT ABORT: ${error}`);
    throw error;
}

const run24InstalledListeners = [];
let run24Finished = false;
let run24Captured = false;
let timeoutGuard = null;

const cleanupRun24 = function(reason) {
    if (run24Finished) {
        return;
    }
    run24Finished = true;
    if (timeoutGuard !== null) {
        clearTimeout(timeoutGuard);
        timeoutGuard = null;
    }
    while (run24InstalledListeners.length > 0) {
        const listener = run24InstalledListeners.pop();
        try {
            listener.detach();
        } catch (_) {}
    }
    console.log(`[CrossLab Probe] Run24 detached all hooks (reason: ${reason})`);
};

const requiredAttach = function(address, label, callbacks) {
    if (!address || address.isNull()) {
        cleanupRun24(`cannot resolve ${label}`);
        throw new Error(`RUN24 PREFLIGHT ABORT: cannot resolve ${label}`);
    }
    try {
        const listener = Interceptor.attach(address, callbacks);
        run24InstalledListeners.push(listener);
        console.log(`  [+] Attached ${label} at ${address}`);
        return listener;
    } catch (error) {
        cleanupRun24(`required hook failed: ${label}`);
        throw new Error(`RUN24 PREFLIGHT ABORT: required hook failed: ${label}: ${error}`);
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

// Preflight target function entry: Despair::PeerSteam::CloseChannel (RVA +0x923f90)
const peerSteamCloseTarget = run24MainModule.base.add(run24ReviewedManifest.fear3.peerSteamCloseRva);
if (!bytesMatch(peerSteamCloseTarget, run24ReviewedManifest.fear3.peerSteamCloseEntryBytes)) {
    throw new Error(`RUN24 PREFLIGHT ABORT: Despair::PeerSteam::CloseChannel entry byte signature mismatch at F.E.A.R. 3.exe+0x${run24ReviewedManifest.fear3.peerSteamCloseRva.toString(16)}`);
}
console.log(`[CrossLab Probe] Run24 live target preflight OK target=${peerSteamCloseTarget} authority=F.E.A.R. 3.exe+0x${run24ReviewedManifest.fear3.peerSteamCloseRva.toString(16)} entry_bytes=OK`);

// Arm the 600s Safety Timeout Guard BEFORE hook installation
timeoutGuard = setTimeout(function() {
    cleanupRun24("600s safety timeout reached");
}, 600000);

// Primary Run 24 Hook: Despair::PeerSteam::CloseChannel (RVA +0x923f90)
requiredAttach(peerSteamCloseTarget, "Run24 Despair::PeerSteam::CloseChannel entry target", {
    onEnter: function(args) {
        if (run24Finished || run24Captured) {
            return;
        }
        const retAddr = this.returnAddress;
        const peerSteamThis = this.context.ecx;
        const endpointDescriptorPtr = args[0];

        let channel = -1;
        try {
            channel = peerSteamThis.add(6).readU16();
        } catch (_) {}

        // Filter synchronously for Channel 4101
        if (channel !== 4101) {
            return;
        }

        // Synchronous latch: claim one-shot capture immediately before any async or stack work
        if (run24Captured) {
            return;
        }
        run24Captured = true;

        const nowMs = Date.now();
        const tid = Process.getCurrentThreadId();
        let retModule = "<no-module>";
        let retRva = "0x0";
        const owner = Process.findModuleByAddress(retAddr);
        if (owner) {
            retModule = owner.name;
            retRva = `0x${retAddr.sub(owner.base).toString(16)}`;
        }

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
            event: "Run24PeerSteamCloseEvidence",
            timestamp: new Date(nowMs).toISOString(),
            tid: tid,
            channel: channel,
            peer_steam_this: peerSteamThis.toString(),
            endpoint_descriptor_ptr: endpointDescriptorPtr.toString(),
            descriptor_read_ok: descriptorReadOk,
            descriptor_read_error: descriptorReadError,
            descriptor_fields: {
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
        console.log("[Client Probe] Despair::PeerSteam::CloseChannel(4101) entry detected. Detaching Run 24 probe.");

        setImmediate(function() {
            cleanupRun24("PeerSteam::CloseChannel(4101) captured");
        });
    }
});

console.log("[CrossLab Probe] Run 24 probe attached successfully. Waiting for PeerSteam::CloseChannel(4101) event...");