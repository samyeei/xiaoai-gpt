import importlib.util
import pathlib
import unittest

spec = importlib.util.spec_from_file_location('runtime_bundle', pathlib.Path(__file__).with_name('runtime_bundle.py'))
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

class RuntimeBundleTests(unittest.TestCase):
    def test_audio_permission_is_added_without_dropping_node_runtime_requirements(self):
        original = {'com.apple.security.cs.allow-jit': True}
        result = runtime.audio_entitlements(original)
        self.assertTrue(result['com.apple.security.device.audio-input'])
        self.assertTrue(result['com.apple.security.cs.allow-jit'])
        self.assertNotIn('com.apple.security.device.audio-input', original)

    def test_bundle_has_stable_identity_and_microphone_reason(self):
        info = runtime.bundle_info()
        self.assertEqual(info['CFBundleExecutable'], 'node')
        self.assertEqual(info['CFBundleIdentifier'], 'com.LOCAL_USER.xiaoai-native-voice')
        self.assertTrue(info['NSMicrophoneUsageDescription'])
        self.assertTrue(info['LSUIElement'])

    def test_agent_change_preserves_cleanup_and_supervisor_arguments(self):
        values = {'ProgramArguments': ['/original/node', '/root/supervisor.mjs'], 'ExitTimeOut': 60, 'KeepAlive': True}
        updated = runtime.agent_with_runtime(values, '/local/Voice.app/Contents/MacOS/node')
        self.assertEqual(updated['ProgramArguments'], ['/local/Voice.app/Contents/MacOS/node', '/root/supervisor.mjs'])
        self.assertEqual(updated['ExitTimeOut'], 60)
        self.assertEqual(values['ProgramArguments'][0], '/original/node')

if __name__ == '__main__':
    unittest.main()
