"""Vendor the pure-JS dependency, verified against package-lock integrity."""
import base64
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

root = Path(__file__).resolve().parents[1]
bridge = root / 'deploy/bridge'
dependency = json.loads((bridge / 'package-lock.json').read_text())['packages']['node_modules/ws']
with urllib.request.urlopen(dependency['resolved'], timeout=30) as response:
    data = response.read()
algorithm, expected = dependency['integrity'].split('-', 1)
assert algorithm == 'sha512'
assert base64.b64encode(hashlib.sha512(data).digest()).decode() == expected
destination = bridge / 'vendor/ws'
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    for member in archive:
        parts = Path(member.name).parts
        assert parts[0] == 'package' and '..' not in parts
        if not member.isfile():
            continue
        path = destination.joinpath(*parts[1:])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(archive.extractfile(member).read())
assert json.loads((destination / 'package.json').read_text())['version'] == dependency['version']
print('Vendored ws', dependency['version'], '; package-lock SHA512 verified')
