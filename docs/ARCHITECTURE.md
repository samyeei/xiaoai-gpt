# Architecture / 架构

## Current Mac route / 当前 Mac 路线

```text
LX06 client (events + microphone PCM)
  -> LAN WebSocket :4399 -> bridge + local sherpa-onnx recognition
  -> single question: Codex text app-server -> native speaker TTS
  -> continuous: Codex realtime app-server + WebRTC/Opus
       -> Python media -> restricted SSH aplay -> originating LX06
```

`mac/unified-service` owns ASR/bridge/text children. `mac/realtime-voice` owns realtime session/media/playback. `mac/native-voice/supervisor.mjs` remains idle for compatibility/occupancy checks; it is not the active desktop-voice path. Historical Muse/ESP32/NAS scripts are retained as source references, not supported default installation steps.

`config/speakers.json` selects single/multiple; single is the public default. Multiple mode uses a shared conversation lease and routes output by registered device ID. It does not support simultaneous AI conversations. Multi-speaker breadth of human acceptance remains limited.

Voice playback gates microphone upload (half duplex). The 600ms startup buffer, bounded Opus repair and reorder logic improve continuity but do not guarantee zero stutter or natural full-duplex interruption. Native XiaoAI wake remains the tested playback stop mechanism.

## Source map / 源码位置

| Directory | Purpose |
| --- | --- |
| config | Wake words, control commands, model/voice, speaker registry |
| deploy/bridge | Device protocol, routing, lease, single/continuous control |
| deploy/voice | Local KWS/ASR, segmentation and wake shadow diagnostics |
| mac/codex-service | Authenticated text tasks, account app-server RPC, preset loader |
| mac/realtime-voice | WebRTC audio, fixed player auth, session/exit lifecycle |
| mac/unified-service | Child lifecycle, local control, feature flags |
| mac/native-voice | Historical desktop audio plus idle supervisor compatibility |
| mac/muse-service | Historical independent Muse experiments; pairing not validated on Mac |
| tools | Historical deployment/diagnostic helpers; inspect before use |

## Local interfaces / 本地接口

Speaker ingress4399 is on the LAN; health4398 and recognition4400/4401 should be local. Text4411 and its control4412, unified4413, idle Muse4414, native compatibility4417, realtime4418 and internal audio4419 must be scoped per source/config, with admin controls kept on loopback. Do not expose these as a public API.

## Validation boundary / 验收边界

The source derives from a personally accepted Mac/LX06 setup. Clean install on a second Mac, other client forks/models, full machine restoration and long unattended operation are not independently proven. Keep test evidence and human listening evidence separate. No Codex credentials, model weights, raw device logs or private restoration archives belong in the repository.
