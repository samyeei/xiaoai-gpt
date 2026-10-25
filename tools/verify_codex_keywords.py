#!/usr/bin/env python3
"""Local synthetic smoke test; no microphone, network, ASR, or bridge calls.

Run with the Mac voice venv. macOS say and afconvert create bounded mono 16k WAVs.
This is model feasibility evidence, never human/device acceptance evidence.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/voice'))
from keyword_routes import wake_packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/2026-10-07/codex-voice')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    k = ROOT / 'deploy/models/kws'
    spotter = sherpa_onnx.KeywordSpotter(
        tokens=str(k / 'tokens.txt'),
        encoder=str(k / 'encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),
        decoder=str(k / 'decoder-epoch-13-avg-2-chunk-16-left-64.onnx'),
        joiner=str(k / 'joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),
        keywords_file=str(ROOT / 'deploy/voice/keywords.txt'),
        num_threads=1, provider='cpu', max_active_paths=4,
        keywords_score=1.5, keywords_threshold=.25, num_trailing_blanks=1)
    cases = [('HEY_MUSE', 'Hey Muse', 'Samantha'),
             ('HEY_CODEX', 'Hey Codex', 'Samantha'),
             ('HEY_GPT', 'Hey G P T', 'Samantha'),
             ('HEY_LUKA', 'hey 卢卡', 'Tingting'),
             ('NO_WAKE', 'The weather is sunny today', 'Samantha')]
    results = []
    for label, text, voice in cases:
        aiff = args.output / f'{label}.aiff'
        wav = args.output / f'{label}.wav'
        subprocess.run(['say', '-v', voice, '-r', '150', '-o', str(aiff), text], check=True)
        subprocess.run(['afconvert', str(aiff), str(wav), '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1'], check=True)
        with wave.open(str(wav)) as audio:
            assert (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) == (1, 16000, 2)
            samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32) / 32768
        if label == 'HEY_LUKA':
            # Preserve English hey and Chinese 卢卡 instead of asking one voice to switch languages.
            parts = []
            for part, part_voice in [('hey', 'Samantha'), ('卢卡', 'Tingting')]:
                source = args.output / f'luka-{part_voice}.aiff'
                target = args.output / f'luka-{part_voice}.wav'
                subprocess.run(['say', '-v', part_voice, '-r', '150', '-o', str(source), part], check=True)
                subprocess.run(['afconvert', str(source), str(target), '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1'], check=True)
                with wave.open(str(target)) as audio:
                    data = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2')
                voiced = np.flatnonzero(np.abs(data.astype(np.int32)) > 100)
                parts.append(data[max(0, voiced[0]-800):voiced[-1]+800])
            mixed = np.concatenate(parts)
            with wave.open(str(wav), 'wb') as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                audio.writeframes(mixed.tobytes())
            samples = mixed.astype(np.float32) / 32768
            voice = 'Samantha hey + Tingting 卢卡'
        samples = np.concatenate((np.zeros(8000, dtype=np.float32), samples, np.zeros(24000, dtype=np.float32)))
        stream = spotter.create_stream()
        detected = []
        for offset in range(0, len(samples), 320):
            stream.accept_waveform(16000, samples[offset:offset + 320])
            while spotter.is_ready(stream):
                spotter.decode_stream(stream)
                keyword = spotter.get_result(stream)
                if keyword:
                    detected.append(keyword)
                    spotter.reset_stream(stream)
        packets = [wake_packet(x) for x in detected]
        passed = detected == [label] if label != 'NO_WAKE' else not detected
        results.append(dict(expected=label, phrase=text, voice=voice, detected=detected,
                            wake_packets=packets, passed=passed, evidence='synthetic_only', wav=str(wav)))
    report = dict(python=sys.version.split()[0], sherpa_onnx=sherpa_onnx.__version__,
                  results=results, human_audio_verified=False, device_verified=False)
    (args.output / 'synthetic-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(x['passed'] for x in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
