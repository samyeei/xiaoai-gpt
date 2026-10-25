"""Shared public wake configuration; runtime credentials never belong here."""
import json
import os
import re
import unicodedata
from pathlib import Path

DEFAULT_PATH = (Path(__file__).resolve().parent / '../../config/wake-words.json').resolve()


def normalize(text):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', str(text))).lower()


def load_config(path=None):
    p = Path(path or os.environ.get('WAKE_WORDS_CONFIG') or DEFAULT_PATH)
    if p.stat().st_size > 65536:
        raise ValueError('Wake configuration too large')
    c = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(c, dict) or set(c) != {'version', 'routes'} or type(c['version']) is not int or c['version'] != 1:
        raise ValueError('Invalid wake configuration')
    if not isinstance(c['routes'], list) or not 1 <= len(c['routes']) <= 32:
        raise ValueError('Invalid wake routes')
    labels, phrases = set(), set()
    for row in c['routes']:
        if not isinstance(row, dict) or set(row) != {'label', 'backend', 'enabled', 'phrases', 'kws_tokens'}:
            raise ValueError('Invalid wake route fields')
        label = row['label']
        if not isinstance(label, str) or not re.fullmatch('[A-Z][A-Z0-9_]{0,47}', label) or label in labels:
            raise ValueError('Invalid or duplicate wake label')
        labels.add(label)
        if row['backend'] not in ('codex', 'muse') or type(row['enabled']) is not bool:
            raise ValueError('Invalid backend or enabled flag')
        if not isinstance(row['phrases'], list) or not 1 <= len(row['phrases']) <= 16:
            raise ValueError('Invalid wake phrases')
        for phrase in row['phrases']:
            if not isinstance(phrase, str) or not 1 <= len(phrase) <= 80 or not normalize(phrase) or normalize(phrase) in phrases:
                raise ValueError('Invalid or duplicate normalized wake phrase')
            phrases.add(normalize(phrase))
        phones = row['kws_tokens']
        if not isinstance(phones, list) or not 1 <= len(phones) <= 128 or any(not isinstance(x, str) or not re.fullmatch(r'[^\s@:$#]{1,32}', x) for x in phones):
            raise ValueError('Invalid keyword pronunciation')
    if not any(row['enabled'] for row in c['routes']):
        raise ValueError('At least one wake route must be enabled')
    return c


def match_phrase(text, config):
    phrase = normalize(text)
    for row in config['routes']:
        if row['enabled'] and phrase in {normalize(p) for p in row['phrases']}:
            return row['label']
    return None


def keyword_lines(config, tokens):
    lines = []
    for row in config['routes']:
        if not row['enabled']:
            continue
        if not all(token in tokens for token in row['kws_tokens']):
            raise ValueError('Wake pronunciation contains tokens unavailable in the installed model')
        lines.append(' '.join(row['kws_tokens']) + ' @' + row['label'])
    return lines
