"""Build a task-owned audio runtime; never re-sign the shared Node binary.

macOS attributes child CoreAudio capture to the responsible supervisor.
The app identity must declare audio input and a reason before macOS can ask
the user for microphone access. Installation does not grant that permission.
"""
import copy
import hashlib
import pathlib
import plistlib
import shutil
import subprocess


def audio_entitlements(original):
    result = dict(original)
    result['com.apple.security.device.audio-input'] = True
    return result


def bundle_info():
    return dict(CFBundleExecutable='node',
                CFBundleIdentifier='com.LOCAL_USER.xiaoai-native-voice',
                CFBundleName='Xiaoai Native Voice', CFBundleDisplayName='小爱语音转接',
                CFBundlePackageType='APPL', CFBundleVersion='1',
                NSMicrophoneUsageDescription='读取 BlackHole 虚拟音频输入，将 Codex 的回答声音送回小爱音箱。',
                LSUIElement=True)


def agent_with_runtime(values, executable):
    result = copy.deepcopy(values)
    result['ProgramArguments'][0] = str(executable)
    return result


def build():
    home = pathlib.Path.home()
    source = (home / '.local/bin/node').resolve(strict=True)
    app = home / 'Applications/Xiaoai Native Voice.app'
    if app.exists():
        raise RuntimeError('Audio runtime already exists; refusing replacement')
    before = hashlib.sha256(source.read_bytes()).digest()
    entitlements = subprocess.run(['/usr/bin/codesign', '-d', '--entitlements', ':-', str(source)],
                                 check=True, capture_output=True).stdout
    parsed = plistlib.loads(entitlements)
    binary = app / 'Contents/MacOS/node'
    resources = app / 'Contents/Resources'
    try:
        binary.parent.mkdir(parents=True)
        resources.mkdir()
        shutil.copy2(source, binary)
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(bundle_info()))
        permission_file = resources / 'audio-entitlements.plist'
        permission_file.write_bytes(plistlib.dumps(audio_entitlements(parsed)))
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', '--options', 'runtime',
                        '--entitlements', str(permission_file), str(app)], check=True)
        subprocess.run(['/usr/bin/codesign', '--verify', '--strict', str(app)], check=True)
        if hashlib.sha256(source.read_bytes()).digest() != before:
            raise RuntimeError('Shared runtime changed unexpectedly')
    except BaseException:
        shutil.rmtree(app)
        raise
    return binary


if __name__ == '__main__':
    print(build())
