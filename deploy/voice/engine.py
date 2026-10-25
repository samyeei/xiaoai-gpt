"""Bounded utterance collection and CPU-only keyword/ASR models."""
from collections import deque
from pathlib import Path
import os
import numpy as np

RATE = 16000

class Utterance:
    def __init__(self, threshold=60, silence_seconds=1.1, max_seconds=15, wait_seconds=10):
        self.threshold = threshold
        self.silence_limit = int(silence_seconds * RATE)
        self.maximum = int(max_seconds * RATE)
        self.wait_limit = int(wait_seconds * RATE)
        self.pre = deque(maxlen=5)
        self.frames = []
        self.total = self.speech = self.silence = 0
        self.started = False
        self.peak_rms = 0.0

    def diagnostics(self):
        return dict(peak_rms=round(self.peak_rms, 1), threshold=self.threshold,
                    voiced_seconds=round(self.speech / RATE, 3), started=self.started)

    def feed(self, samples):
        self.total += len(samples)
        energy = float(np.sqrt(np.mean(samples.astype(np.float32)**2)))
        self.peak_rms = max(self.peak_rms, energy)
        voiced = energy >= self.threshold
        if not self.started:
            self.pre.append(samples.copy())
            if voiced:
                self.started = True
                self.frames.extend(self.pre)
                self.speech += len(samples)
            elif self.total >= self.wait_limit:
                return 'timeout'
        else:
            self.frames.append(samples.copy())
            self.speech += len(samples) if voiced else 0
            self.silence = 0 if voiced else self.silence + len(samples)
            if self.total >= self.maximum or self.silence >= self.silence_limit:
                return 'complete' if self.speech >= int(.25 * RATE) else 'timeout'
        return None

    def audio(self):
        return np.concatenate(self.frames).astype(np.float32) / 32768

class Models:
    def __init__(self, directory):
        import sherpa_onnx
        root = Path(directory)
        self.model_root = root
        k = root / 'kws'
        import tempfile
        from wake_config import load_config, keyword_lines
        self.keyword_lines = keyword_lines(load_config(), {line.split()[0] for line in (k / 'tokens.txt').read_text().splitlines()})
        with tempfile.NamedTemporaryFile(mode='w', suffix='.keywords', encoding='utf-8') as f:
            f.write('\n'.join(self.keyword_lines) + '\n'); f.flush()
            self.kws = sherpa_onnx.KeywordSpotter(
            tokens=str(k / 'tokens.txt'),
            encoder=str(k / 'encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),
            decoder=str(k / 'decoder-epoch-13-avg-2-chunk-16-left-64.onnx'),
            joiner=str(k / 'joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),
            keywords_file=f.name,
            num_threads=1, provider='cpu', max_active_paths=4,
            keywords_score=1.5, keywords_threshold=.25, num_trailing_blanks=1)
        self.asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(root / 'asr/model.int8.onnx'), tokens=str(root / 'asr/tokens.txt'),
            num_threads=1, provider='cpu', language='auto', use_itn=True)

    def calibration_decoder(self, gain=1, score=None, threshold=None):
        import tempfile
        import sherpa_onnx
        from keyword_tuning import candidate_lines, validate_lines, bounded_gain
        k=self.model_root / 'kws'
        lines=candidate_lines(self.keyword_lines,score=score,threshold=threshold)
        tokens={line.split()[0] for line in (k/'tokens.txt').read_text().splitlines()}
        validate_lines(lines,tokens)
        with tempfile.NamedTemporaryFile(mode='w',suffix='.keywords',encoding='utf-8') as f:
            f.write('\n'.join(lines)+'\n');f.flush()
            other=Models.__new__(Models)
            other.kws=sherpa_onnx.KeywordSpotter(tokens=str(k/'tokens.txt'),encoder=str(k/'encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),decoder=str(k/'decoder-epoch-13-avg-2-chunk-16-left-64.onnx'),joiner=str(k/'joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx'),keywords_file=f.name,num_threads=1,provider='cpu',max_active_paths=4,keywords_score=1.5,keywords_threshold=.25,num_trailing_blanks=1)
        stream=other.stream()
        return lambda samples:other.keyword(stream,bounded_gain(samples,gain))

    def transcribe(self, samples):
        stream = self.asr.create_stream()
        stream.accept_waveform(RATE, samples)
        self.asr.decode_stream(stream)
        return stream.result.text.strip()

    def stream(self):
        return self.kws.create_stream()

    def keyword(self, stream, samples):
        stream.accept_waveform(RATE, samples.astype(np.float32) / 32768)
        while self.kws.is_ready(stream):
            self.kws.decode_stream(stream)
            result = self.kws.get_result(stream)
            if result:
                self.kws.reset_stream(stream)
                return result
        return None
