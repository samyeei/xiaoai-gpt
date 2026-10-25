import {
  readFileSync,
  existsSync,
  mkdirSync,
  chmodSync,
  writeFileSync,
  renameSync,
  openSync,
  fsyncSync,
  closeSync,
} from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:http";
import { timingSafeEqual, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { ChildGroup, signalOwned } from "./lifecycle.mjs";
import { nativeAudioOptIn } from "../../deploy/bridge/audio-mirror.mjs";
import {configureVoiceFlags,asrWakeTestEnv,asrWakeEnv as permanentAsrWakeEnv} from "./voice-config.mjs";
import { nativeWakeOptIn } from "../../deploy/bridge/native-voice-client.mjs";
import {loadSpeakers} from '../../deploy/bridge/speakers.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const multiSpeaker=loadSpeakers().mode==='multiple';
const privateDir = resolve(root, "mac/unified-service/private"),
  museDir = resolve(root, "mac/muse-service/private");
const codex = JSON.parse(
    readFileSync(resolve(root, "mac/codex-service/private/config.json")),
  ),
  muse = JSON.parse(readFileSync(resolve(museDir, "config.json")));
const python = resolve(root, ".codex-runs/mac-voice-env/bin/python"),
  node = "/Users/YOUR_USER/.local/bin/node";
mkdirSync(privateDir, { recursive: true, mode: 0o700 });
chmodSync(privateDir, 0o700);
const bridge = JSON.parse(
  readFileSync(resolve(root, "deploy/config/bridge.json")),
);
bridge.voice_url = "ws://127.0.0.1:4400";
bridge.calibration_key = codex.admin_key;
// An expired/missing private probe flag must also clear inherited config values.
delete bridge.native_audio_url;
delete bridge.native_audio_expires_at;
try {
  Object.assign(bridge, nativeAudioOptIn(JSON.parse(
    readFileSync(resolve(privateDir, "native-audio.json"), "utf8"),
  )));
} catch { /* Missing or malformed opt-in safely disables the probe. */ }
delete bridge.native_voice;
try {
  const nativeVoice = nativeWakeOptIn(JSON.parse(readFileSync(resolve(privateDir, "native-wake.json"), "utf8")), codex.admin_key);
  if (nativeVoice) bridge.native_voice = nativeVoice;
} catch { /* Private opt-in absent or malformed. */ }
delete bridge.realtime_voice;
try {
  const updated=configureVoiceFlags(bridge,{realtimeFlag:JSON.parse(readFileSync(resolve(privateDir,"realtime-voice.json"),"utf8"))},codex.admin_key);
  if(updated.realtime_voice){delete bridge.native_voice;delete bridge.native_audio_url;delete bridge.native_audio_expires_at;bridge.realtime_voice=updated.realtime_voice;}
}catch{}
bridge.muse = { url: muse.url, key: muse.key };
bridge.codex = {
  ...bridge.codex,
  url: "http://127.0.0.1:" + codex.port,
  key: codex.key,
};
const bridgePath = resolve(privateDir, "bridge.json");
writeFileSync(bridgePath, JSON.stringify(bridge), { mode: 0o600 });
chmodSync(bridgePath, 0o600);
const spec = (command, args, env = {}) => ({ command, args, env, cwd: root });
let asrWakeEnv={};
try{asrWakeEnv=asrWakeTestEnv(JSON.parse(readFileSync(resolve(privateDir,'asr-wake-test.json'),'utf8')));}catch{}
try{asrWakeEnv={...asrWakeEnv,...permanentAsrWakeEnv(JSON.parse(readFileSync(resolve(privateDir,'asr-wake.json'),'utf8')))};}catch{}
const group = new ChildGroup({
  ...(multiSpeaker?{voice_secondary:spec(python,[resolve(root,'deploy/voice/worker.py')],{
    VOICE_HOST:'127.0.0.1',VOICE_PORT:'4401',MODELS_DIR:resolve(root,'deploy/models'),VAD_RMS:'20',...asrWakeEnv
  })}:{}),
  voice: spec(python, [resolve(root, "deploy/voice/worker.py")], {
    VOICE_HOST: "127.0.0.1",
    MODELS_DIR: resolve(root, "deploy/models"),
    VAD_RMS: "20",
    ...asrWakeEnv,
  }),
  muse: spec(python, [
    resolve(root, "mac/muse-service/index.py"),
    "run",
    "--state-dir",
    museDir,
  ]),
  codex: spec(node, [resolve(root, "mac/codex-service/index.mjs")], {
    XIAOAI_UNIFIED: "1",
  }),
  bridge: spec(node, [resolve(root, multiSpeaker?"deploy/bridge/multi-index.mjs":"deploy/bridge/index.mjs")], {
    HEY_MUSE: "1",
    BRIDGE_HOST: process.env.BRIDGE_HOST ?? "192.168.100.106",
    BRIDGE_HEALTH_HOST: "127.0.0.1",
    BRIDGE_CONFIG: bridgePath,
  }),
});
let pairing = null,
  pairState = { state: "idle" },
  stopping = false;
async function remote(url, key, path, body) {
  const r = await fetch(url + path, {
    method: body ? "POST" : "GET",
    headers: {
      Authorization: "Bearer " + key,
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(5000),
  });
  if (!r.ok) throw Error("Backend unavailable");
  return r.json();
}
async function health() {
  const probe = async (url, key) => {
    try {
      return await remote(url, key, "/health");
    } catch {
      return { ready: false, state: "unavailable" };
    }
  };
  const [m, c, b] = await Promise.all([
    probe(muse.url, muse.key),
    probe("http://127.0.0.1:" + codex.port, codex.key),
    probe("http://127.0.0.1:4398", ""),
  ]);
  return {
    children: group.status(),
    muse: m,
    codex: c,
    voice: b,
    pairing: pairState,
    sdk_token_ready:
      existsSync(resolve(museDir, "sdk_token")) &&
      readFileSync(resolve(museDir, "sdk_token"), "utf8").trim().length > 0,
  };
}
const server = createServer(async (req, res) => {
  const send = (status, data) => {
    res.writeHead(status, {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
    });
    res.end(JSON.stringify(data));
  };
  try {
    const expected = "127.0.0.1:4413";
    if (
      req.headers.host !== expected ||
      (req.headers.origin && req.headers.origin !== "http://" + expected)
    )
      return send(403, { error: "Local origin required" });
    const a = Buffer.from(req.headers.authorization ?? ""),
      b = Buffer.from("Bearer " + codex.admin_key);
    if (a.length !== b.length || !timingSafeEqual(a, b))
      return send(401, { error: "Unauthorized" });
    if (req.method === "GET" && req.url === "/status")
      return send(200, await health());
    let data = {},
      size = 0,
      chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 16384) return send(413, { error: "Request too large" });
      chunks.push(chunk);
    }
    if (size) data = JSON.parse(Buffer.concat(chunks));
    if (req.method !== "POST") return send(404, { error: "Not found" });
    if (req.url === "/token") {
      if (pairing || existsSync(resolve(museDir, "pairing.json")))
        return send(409, { error: "Pairing state already active" });
      if (
        typeof data.token !== "string" ||
        !/^mgst_[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/.test(data.token)
      )
        return send(400, { error: "Invalid SDK token format" });
      const tmp = resolve(museDir, ".sdk-token-" + randomUUID());
      writeFileSync(tmp, data.token + "\n", { mode: 0o600, flag: "wx" });
      const fd = openSync(tmp, "r");
      fsyncSync(fd);
      closeSync(fd);
      renameSync(tmp, resolve(museDir, "sdk_token"));
      return send(200, { ok: true });
    }
    if (req.url === "/pair/start") {
      if (pairing || existsSync(resolve(museDir, "pairing.json")))
        return send(409, { error: "Pairing state already active" });
      if (
        !existsSync(resolve(museDir, "sdk_token")) ||
        !readFileSync(resolve(museDir, "sdk_token"), "utf8").trim()
      )
        return send(400, { error: "SDK token required" });
      pairState = { state: "starting" };
      pairing = spawn(
        python,
        [
          resolve(root, "mac/muse-service/pair.py"),
          "pair",
          "--state-dir",
          museDir,
        ],
        { cwd: root, detached: true, stdio: ["ignore", "pipe", "ignore"] },
      );
      let buffer = "";
      pairing.stdout.on("data", (chunk) => {
        buffer += chunk;
        if (buffer.length > 8192) {
          buffer = "";
          return;
        }
        let n;
        while ((n = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, n);
          buffer = buffer.slice(n + 1);
          try {
            const e = JSON.parse(line);
            if (
              e.pairing === "open" &&
              /^MuseGadget[A-Za-z0-9_-]*$/.test(e.name)
            )
              pairState = { state: "open", name: e.name };
            if (e.pairing === "complete") pairState = { state: "complete" };
          } catch {}
        }
      });
      const pairChild = pairing;
      const ended = () => {
        signalOwned(pairChild, "SIGKILL");
        pairing = null;
        if (pairState.state !== "complete")
          pairState = { state: "stopped_or_failed" };
      };
      pairing.once("exit", ended);
      pairing.once("error", ended);
      return send(200, { ok: true });
    }
    if (req.url === "/pair/stop") {
      if (pairing) {
        const p = pairing;
        signalOwned(p, "SIGTERM");
        const t = setTimeout(() => signalOwned(p, "SIGKILL"), 5000);
        p.once("exit", () => clearTimeout(t));
      }
      return send(200, { ok: true });
    }
    if (req.url === "/muse/ask")
      return send(
        202,
        await remote(muse.url, muse.key, "/requests", {
          request_id: randomUUID(),
          text: data.text,
        }),
      );
    if (req.url === "/muse/get" && /^[a-zA-Z0-9_-]{1,80}$/.test(data.id))
      return send(
        200,
        await remote(muse.url, muse.key, "/requests/" + data.id),
      );
    return send(404, { error: "Not found" });
  } catch {
    return send(503, { error: "Operation unavailable" });
  }
});
server.requestTimeout = 10000;
server.headersTimeout = 10000;
server.maxHeadersCount = 32;
async function stopPairing() {
  if (!pairing) return;
  const child = pairing;
  await new Promise((resolve) => {
    const timer = setTimeout(() => signalOwned(child, "SIGKILL"), 5000);
    child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
    signalOwned(child, "SIGTERM");
  });
}
async function stop() {
  if (stopping) return;
  stopping = true;
  group.freeze();
  server.close();
  server.closeAllConnections();
  await group.shutdownWith(stopPairing);
}
for (const s of ["SIGINT", "SIGTERM"]) process.on(s, () => void stop());
server.on("error", () => {
  process.exitCode = 1;
  void stop();
});
server.listen(4413, "127.0.0.1", () => {
  for (const name of Object.keys(group.specs)) group.start(name);
});
