"""Accept only the exact keyword labels configured for this worker."""
ALLOWED_KEYWORDS = frozenset(('HEY_MUSE', 'HEY_CODEX', 'HEY_GPT', 'HEY_LUKA'))


def wake_packet(keyword, allowed=ALLOWED_KEYWORDS):
    if not isinstance(keyword, str) or keyword not in allowed:
        return None
    return {'type': 'wake', 'keyword': keyword}
