/**
 * FEAR 3 Steam P2P Diagnostic Probe - Run 22 (Entry-Only Caller Evidence)
 * 
 * Strict entry-only Interceptor instrumentation targeting CloseP2PChannelWithUser (Slot 5).
 * Completely eliminates Stalker and mid-function hooks to guarantee stability.
 * 
 * Usage:
 *   frida -n "F.E.A.R. 3.exe" -l fear3_run22_probe.js
 */

console.log("[CrossLab Probe] Initializing Run 22 entry-only diagnostic probe in F.E.A.R. 3...");

const steamApi = Process.findModuleByName("steam_api.dll") || Process.findModuleByName("steam_api64.dll");

if (!steamApi) {
    console.log("[CrossLab Probe] RUN22 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded");
    throw new Error("RUN22 PREFLIGHT ABORT: required steam_api.dll/steam_api64.dll is not loaded");
}

const run22ReviewedManifest = {
    fear3: {
        moduleName: "F.E.A.R. 3.exe",
        sha256: "b9aefdbee81d92296532a17b2032a5731e40026d04026a8194cb9125a6a6c915",
        peTimestamp: 0x4e0d0b76,
        sizeOfImage: 0x15e2000
    },
    steamclient: {
        moduleName: "steamclient.dll",
        sha256: "75de00444dede8c95a94b3c283a0292f33e40005e29c669fd112cbb9d44876d7",
        peTimestamp: 0x6a70ef0e,
        sizeOfImage: 0x1498000,
        closeChannelRva: 0x611960
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
    console.log(`[CrossLab Probe] Run22 manifest OK ${module.name} sha256=${sha256} pe_timestamp=0x${identity.peTimestamp.toString(16)} size_of_image=0x${identity.sizeOfImage.toString(16)}`);
};

const run22MainModule = Process.mainModule;
const run22SteamClient = Process.findModuleByName("steamclient.dll");
try {
    if (!run22MainModule) {
        throw new Error("required main module is not available");
    }
    validateReviewedImage(run22MainModule, run22ReviewedManifest.fear3);
    validateReviewedImage(run22SteamClient, run22ReviewedManifest.steamclient);
    console.log("[CrossLab Probe] Run22 preflight manifest OK; stalker-free entry-only mode active");
} catch (error) {
    console.log(`[CrossLab Probe] RUN22 PREFLIGHT ABORT: ${error}`);
    throw error;
}

const run22InstalledListeners = [];
let run22Finished = false;

const untrackListener = function(listener) {
    const index = run22InstalledListeners.indexOf(listener);
    if (index !== -1) {
        run22InstalledListeners.splice(index, 1);
    }
};

const trackedAttach = function(address, callbacks) {
    const listener = Interceptor.attach(address, callbacks);
    run22InstalledListeners.push(listener);
    return listener;
};

const cleanupRun22 = function(reason) {
    run22Finished = true;
    while (run22InstalledListeners.length > 0) {
        const listener = run22InstalledListeners.pop();
        try {
            listener.detach();
        } catch (_) {}
    }
    console.log(`[CrossLab Probe] Run22 detached all hooks (reason: ${reason})`);
};

const findExport = function(name) {
    if (typeof steamApi.findExportByName === "function") {
        return steamApi.findExportByName(name);
    }
    if (typeof Module.findExportByName === "function") {
        return Module.findExportByName(steamApi.name, name);
    }
    return null;
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

const steamIdKey = function(low, high) {
    return `0x${high.toString(16).padStart(8, "0")}${low.toString(16).padStart(8, "0")}`;
};

// Legacy vtable discovery
let legacyNetworkingVtable = null;
const networkingFactory = findExport("SteamNetworking");
if (networkingFactory) {
    const getNetworking = new NativeFunction(networkingFactory, "pointer", []);
    const networking = getNetworking();
    if (!networking.isNull()) {
        legacyNetworkingVtable = networking.readPointer();
        console.log(`[CrossLab Probe] Legacy ISteamNetworking vtable at ${legacyNetworkingVtable}`);
    }
}

if (!legacyNetworkingVtable || Process.pointerSize !== 4) {
    throw new Error("RUN22 PREFLIGHT ABORT: reviewed x86 legacy ISteamNetworking vtable unavailable");
}

// Preflight target vtable slot 5 (CloseP2PChannelWithUser)
const closeChannelTarget = legacyNetworkingVtable.add(5 * Process.pointerSize).readPointer();
const closeOwner = Process.findModuleByAddress(closeChannelTarget);
if (!closeOwner || closeOwner.name.toLowerCase() !== run22ReviewedManifest.steamclient.moduleName.toLowerCase()) {
    throw new Error(`RUN22 PREFLIGHT ABORT: CloseP2PChannelWithUser target ${closeChannelTarget} owner=${closeOwner ? closeOwner.name : "none"}`);
}
const closeTargetRva = closeChannelTarget.sub(closeOwner.base).toUInt32();
if (closeTargetRva !== run22ReviewedManifest.steamclient.closeChannelRva) {
    throw new Error(`RUN22 PREFLIGHT ABORT: CloseP2PChannelWithUser target ${closeOwner.name}+0x${closeTargetRva.toString(16)} expected +0x${run22ReviewedManifest.steamclient.closeChannelRva.toString(16)}`);
}
console.log(`[CrossLab Probe] Run22 live-owner preflight OK target=${closeChannelTarget} authority=${closeOwner.name}+0x${closeTargetRva.toString(16)}`);

// Primary Run 22 Hook: CloseP2PChannelWithUser (Slot 5)
trackedAttach(closeChannelTarget, {
    onEnter: function(args) {
        if (run22Finished) return;
        const nowMs = Date.now();
        const tid = Process.getCurrentThreadId();
        const retAddr = this.returnAddress;
        let retModule = "<no-module>";
        let retRva = "0x0";
        const owner = Process.findModuleByAddress(retAddr);
        if (owner) {
            retModule = owner.name;
            retRva = `0x${retAddr.sub(owner.base).toString(16)}`;
        }

        const remoteLow = args[0].toUInt32();
        const remoteHigh = args[1].toUInt32();
        const channel = args[2].toInt32();

        const evidence = {
            event: "Run22CloseP2PChannelEvidence",
            timestamp: new Date(nowMs).toISOString(),
            tid: tid,
            channel: channel,
            remote: steamIdKey(remoteLow, remoteHigh),
            return_address: {
                raw: retAddr.toString(),
                module: retModule,
                rva: retRva
            },
            backtrace: stackTrace(this.context, 12)
        };

        console.log(`[Client Probe] ${JSON.stringify(evidence)}`);

        // If channel 4101 (control channel) is closed, capture once and cleanly detach
        if (channel === 4101) {
            console.log("[Client Probe] Control channel 4101 close detected. Detaching Run 22 probe.");
            setImmediate(function() {
                cleanupRun22("control channel 4101 captured");
            });
        }
    }
});

// Secondary sparse hook: CloseP2PSessionWithUser (Slot 4)
const closeSessionTarget = legacyNetworkingVtable.add(4 * Process.pointerSize).readPointer();
trackedAttach(closeSessionTarget, {
    onEnter: function(args) {
        if (run22Finished) return;
        const retAddr = this.returnAddress;
        let retModule = "<no-module>";
        let retRva = "0x0";
        const owner = Process.findModuleByAddress(retAddr);
        if (owner) {
            retModule = owner.name;
            retRva = `0x${retAddr.sub(owner.base).toString(16)}`;
        }
        const remoteLow = args[0].toUInt32();
        const remoteHigh = args[1].toUInt32();
        console.log(`[Client Probe] ${new Date().toISOString()} CloseP2PSessionWithUser remote=${steamIdKey(remoteLow, remoteHigh)} caller=${retModule}+${retRva}`);
    }
});

// Hard 180s Safety Timeout Guard
const timeoutGuard = setTimeout(function() {
    cleanupRun22("180s safety timeout reached");
}, 180000);

console.log("[CrossLab Probe] Run 22 probe attached successfully. Waiting for session events...");