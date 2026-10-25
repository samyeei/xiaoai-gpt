"""Use the existing low-noise workflow with the intact local CMake install."""
import os
from pathlib import Path
import runpy
import sys

workspace = Path('D:/AI Job/mosaico')
os.chdir(workspace)
os.environ['PYTHONUTF8'] = '1'
os.environ['IDF_TOOLS_PATH'] = str(workspace / '.codex-runs/idf-tools')
os.environ.pop('IDF_PYTHON_ENV_PATH', None)
sys.path.insert(0, str(workspace / 'submodule/esp-mosaico-utils/mosaico-tools/tools'))
import mosaico_cli.host as host
original = host.prepare_idf_environment
def prepare(*args, **kwargs):
    result = original(*args, **kwargs)
    result.values['PATH'] = 'C:/Users/HP/.espressif/tools/cmake/3.30.2/bin;' + result.values['PATH']
    return result
host.prepare_idf_environment = prepare
sys.argv = ['runner', '--project', str(workspace / 'projects/muse_companion'), 'build']
runpy.run_path(str(workspace / 'submodule/esp-mosaico-utils/mosaico-tools/skills/idf-low-noise-build/scripts/idf_low_noise_build.py'), run_name='__main__')
