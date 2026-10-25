"""Create a separate private update bundle, leaving the working old ZIP intact."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DEPLOY=ROOT/'deploy'
ART=ROOT/'artifacts/2026-10-06/hey-muse'
SELECTED={
    'kws': ['encoder-epoch-13-avg-2-chunk-16-left-64.int8.onnx',
            'decoder-epoch-13-avg-2-chunk-16-left-64.onnx',
            'joiner-epoch-13-avg-2-chunk-16-left-64.int8.onnx','tokens.txt','en.phone'],
    'asr': ['model.int8.onnx','tokens.txt','LICENSE','README.md'],
}
capture=json.loads((ART/'transport-acceptance.json').read_text())
pipeline=json.loads((ART/'pipeline-acceptance.json').read_text())
assert capture['frames']>0 and capture['low16_nonzero']==0
assert 'Playing' in capture['playing'] and 'Idle' in capture['playing']
assert pipeline['real_esp32_muse_reply'] and pipeline['synthetic_wake'] and pipeline['local_asr']
manifest=[]
for kind,names in SELECTED.items():
    for name in names:
        path=DEPLOY/'models'/kind/name
        manifest.append(dict(path=str(path.relative_to(DEPLOY/'models')).replace('\\','/'),
                             bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
(DEPLOY/'models/manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
status=json.loads((DEPLOY/'deployment-status.json').read_text())
status.update(nas_deployed=True,lx06_conversation_verified=True,node_tests_passed=17,
              conversation_evidence='User confirmed the original native-wake Muse reply without double answering',
              hey_muse=dict(real_lx06_transport_capture=True,real_lx06_tts_events=True,
                            synthetic_keyword_verified=True,local_asr_verified=True,
                            real_muse_pipeline_verified=True,python_endpoint_tests_passed=3,
                            nas_linux_build_verified=False,updated_nas_deployed=False,
                            human_wake_verified=False,physical_full_conversation_verified=False))
(DEPLOY/'deployment-status.json').write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8')
archive=ROOT/'xiaoai-muse-HeyMuse-群晖更新包.zip'
selected={f'models/{kind}/{name}' for kind,names in SELECTED.items() for name in names}
selected.update({'models/manifest.json','models/sources.json'})
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for path in sorted(DEPLOY.rglob('*')):
        if not path.is_file() or 'node_modules' in path.parts or '__pycache__' in path.parts:
            continue
        relative=path.relative_to(DEPLOY).as_posix()
        if relative.startswith('models/') and relative not in selected: continue
        if path.suffix=='.zip': continue
        z.write(path,relative)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert {'compose.yaml','README_HEY_MUSE.md','config/bridge.json','bridge/package-lock.json',
            'voice/worker.py','models/asr/model.int8.onnx'}<=set(z.namelist())
report=dict(archive=str(archive),bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            contains_private_lan_key=True)
(ART/'package.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
