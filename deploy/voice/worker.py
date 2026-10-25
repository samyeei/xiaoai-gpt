"""Audio remains in RAM; only a final transcript goes to the existing Muse bridge."""
import asyncio
import json
import os
import time
import numpy as np
from websockets.asyncio.server import serve
from engine import Models, Utterance
from keyword_routes import wake_packet
from wake_diagnostics import WakeDiagnostics
from wake_calibration import WakeCalibration
from asr_wake_shadow import AsrWakeShadow, wake_phrase, normalized_phrase
from wake_config import load_config, match_phrase

async def main():
    wake_config = load_config()
    allowed_keywords = {row['label'] for row in wake_config['routes'] if row['enabled']}
    models = await asyncio.to_thread(Models, os.environ.get('MODELS_DIR', '/models'))
    try:
        test_expiry=float(os.environ.get('ASR_WAKE_TEST_EXPIRES_AT','0'))
        if not time.time()<test_expiry<=time.time()+1200:test_expiry=0
    except (ValueError,TypeError):test_expiry=0
    permanent_wake = os.environ.get('ASR_WAKE_ENABLED') == '1'
    def auxiliary_wake_active():
        return permanent_wake or time.time()<test_expiry
    connected = False

    async def connection(ws):
        nonlocal connected
        if connected:
            await ws.close(1013, 'One audio bridge only')
            return
        connected = True
        state = 'paused'
        session = None
        stream = models.stream()
        utterance = None
        pcm = bytearray()
        metrics = dict(models_ready=True, audio_frames=0, rms=0, wake_count=0, asr_count=0)
        last_metrics = 0
        diagnostics = WakeDiagnostics()
        calibration = None
        calibration_id = None
        asr_shadow = None
        live_shadow = AsrWakeShadow()
        tasks = set()
        revision = 0
        recognition_busy = False

        async def emit(packet):
            await ws.send(json.dumps(packet, ensure_ascii=False))

        async def recognize(audio, old_session, old_revision):
            nonlocal recognition_busy
            try:
                text = await asyncio.to_thread(models.transcribe, audio)
                if old_revision == revision:
                    metrics['asr_count'] += 1
                    await emit(dict(type='metrics', data={**metrics, **diagnostics.snapshot(state)}))
                    await emit(dict(type='text', session=old_session, text=text))
            except Exception:
                if old_revision == revision:
                    await emit(dict(type='error', session=old_session))
            finally:
                recognition_busy = False

        def calibration_metrics():
            return {**calibration.stats(), **asr_shadow.stats(), 'calibration_id':calibration_id,
                    'calibration_complete':calibration.samples>=calibration.maximum and not recognition_busy}

        async def recognize_shadow(audio, shadow, old_revision):
            nonlocal recognition_busy, state, stream
            started=time.monotonic()
            try:
                text=await asyncio.to_thread(models.transcribe,audio)
                if old_revision==revision:shadow.record_result(text,time.monotonic()-started,audio)
                del text
            except Exception:
                if old_revision==revision:shadow.errors+=1
            finally:
                recognition_busy=False
                if old_revision==revision:
                    if calibration.samples>=calibration.maximum:asr_shadow.reset();state='idle';stream=models.stream()
                    metrics['calibration']=calibration_metrics()
                    await emit(dict(type='metrics',data={**metrics,**diagnostics.snapshot(state)}))

        async def recognize_live_wake(audio, old_revision):
            nonlocal recognition_busy, state
            try:
                text=await asyncio.to_thread(models.transcribe,audio)
                matched=match_phrase(text,wake_config)
                del text
                if matched and old_revision==revision and state=='idle' and auxiliary_wake_active():
                    state='paused';live_shadow.reset()
                    metrics['wake_count']+=1
                    counter='asr_wake_count' if permanent_wake else 'asr_test_wake_count'
                    metrics[counter]=metrics.get(counter,0)+1
                    diagnostics.wake(matched,int(time.time()*1000))
                    await emit(wake_packet(matched,allowed_keywords))
            except Exception:
                if old_revision==revision:metrics['asr_test_errors']=metrics.get('asr_test_errors',0)+1
            finally:recognition_busy=False

        try:
            await emit(dict(type='metrics', data=metrics))
            async for message in ws:
                if isinstance(message, str):
                    command = json.loads(message)
                    kind = command.get('type')
                    revision += 1
                    live_shadow.reset()
                    pcm.clear()
                    utterance = None
                    session = None
                    if asr_shadow is not None:asr_shadow.reset()
                    if kind == 'calibrate':
                        calibration_id=command.get('session')
                        stream=models.stream()
                        candidate=await asyncio.to_thread(models.calibration_decoder)
                        variants={}
                        for label,gain,score,threshold in [('candidate_gain_4',4,None,None),('candidate_gain_8',8,None,None),('candidate_gain_8_score_3',8,3,.25),('candidate_gain_8_score_3_threshold_015',8,3,.15)]:
                            variants[label]=await asyncio.to_thread(models.calibration_decoder,gain,score,threshold)
                        calibration=WakeCalibration(lambda data:models.keyword(stream,data),candidate,variants=variants)
                        asr_shadow=AsrWakeShadow()
                        state='calibrating'
                        metrics['calibration']=calibration_metrics()
                    elif kind == 'arm':
                        stream = models.stream(); state = 'idle'
                    elif kind == 'listen' and isinstance(command.get('session'), str):
                        if recognition_busy:
                            state = 'paused'
                            await emit(dict(type='timeout', session=command['session']))
                            continue
                        state = 'listening'; session = command['session']
                        utterance = Utterance(threshold=float(os.environ.get('VAD_RMS', '60')))
                    else:
                        state = 'paused'
                    await emit(dict(type='metrics', data={**metrics, **diagnostics.snapshot(state)}))
                    continue
                if len(message) > 64000 or len(message) % 2:
                    await ws.close(1009, 'Invalid audio frame'); break
                pcm.extend(message)
                # Fixed 20ms frames make endpoint timing independent of WS packet sizes.
                while len(pcm) >= 640:
                    samples = np.frombuffer(bytes(pcm[:640]), dtype='<i2')
                    del pcm[:640]
                    metrics['audio_frames'] += 1
                    diagnostics.feed(samples)
                    metrics['rms'] = round(float(np.sqrt(np.mean(samples.astype(np.float32)**2))), 1)
                    if state == 'calibrating':
                        if calibration.samples<calibration.maximum:
                            calibration.feed(samples)
                            if recognition_busy:asr_shadow.busy_samples+=len(samples)
                            else:
                                audio=asr_shadow.feed(samples)
                                if audio is not None:
                                    recognition_busy=True
                                    task=asyncio.create_task(recognize_shadow(audio,asr_shadow,revision))
                                    tasks.add(task);task.add_done_callback(tasks.discard)
                        metrics['calibration']=calibration_metrics()
                        if metrics['calibration']['calibration_complete']:asr_shadow.reset();state='idle';stream=models.stream()
                    elif state == 'idle':
                        keyword = models.keyword(stream, samples)
                        packet = wake_packet(keyword,allowed_keywords)
                        if packet:
                            metrics['wake_count'] += 1; state = 'paused'
                            live_shadow.reset()
                            diagnostics.wake(keyword, int(time.time()*1000))
                            await emit(packet)
                        elif auxiliary_wake_active() and not recognition_busy:
                            audio=live_shadow.feed(samples)
                            if audio is not None:
                                recognition_busy=True
                                task=asyncio.create_task(recognize_live_wake(audio,revision))
                                tasks.add(task);task.add_done_callback(tasks.discard)
                        elif not auxiliary_wake_active():live_shadow.reset()
                    elif state == 'listening':
                        result = utterance.feed(samples)
                        if result:
                            metrics['last_utterance'] = {**utterance.diagnostics(), 'result':result}
                            state = 'paused'
                            if result == 'timeout':
                                await emit(dict(type='timeout', session=session))
                            else:
                                # One bounded recognition at a time; stale results are ignored.
                                recognition_busy = True
                                task = asyncio.create_task(recognize(utterance.audio(), session, revision))
                                tasks.add(task); task.add_done_callback(tasks.discard)
                            utterance = None
                if time.monotonic() - last_metrics >= 2:
                    metrics['asr_wake_enabled']=permanent_wake
                    metrics['asr_wake_active']=auxiliary_wake_active()
                    metrics['asr_wake_test_active']=time.time()<test_expiry
                    metrics['asr_wake_test_expires_at']=test_expiry or None
                    await emit(dict(type='metrics', data={**metrics, **diagnostics.snapshot(state)}))
                    last_metrics = time.monotonic()
        finally:
            revision += 1
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            connected = False

    print('Voice models ready; listening on internal port 4400', flush=True)
    async with serve(connection, os.environ.get('VOICE_HOST', '0.0.0.0'), int(os.environ.get('VOICE_PORT', '4400')),
                     origins=[None] if os.environ.get('VOICE_HOST') == '127.0.0.1' else None,
                     max_size=65536, max_queue=8, ping_interval=20, ping_timeout=20):
        await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
