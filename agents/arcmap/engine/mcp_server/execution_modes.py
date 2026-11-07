"""Explicit per-call inspection routing; legacy tools keep their semantics."""


from pathlib import Path


def rejected(mode, code):
    return {'ok': False, 'code': code, 'requested_mode': mode,
            'execution_lane': None, 'target': None}


def mxd_error(mxd_path):
    if not isinstance(mxd_path, str) or not mxd_path or mxd_path.upper() == 'CURRENT':
        return 'EXPLICIT_MXD_PATH_REQUIRED'
    path = Path(mxd_path)
    if not path.is_absolute():
        return 'ABSOLUTE_MXD_PATH_REQUIRED'
    if path.suffix.lower() != '.mxd':
        return 'MXD_SUFFIX_REQUIRED'
    if not path.is_file():
        return 'MXD_NOT_FOUND'
    return None


def inspect_map(services, mode, mxd_path='', expected_context=None):
    if mode not in ('headless', 'attached'):
        return rejected(mode, 'INVALID_EXECUTION_MODE')
    if mode == 'attached' and mxd_path != '':
        return rejected(mode, 'ATTACHED_DISK_TARGET_FORBIDDEN')
    if mode == 'headless':
        if expected_context is not None:
            return rejected(mode, 'HEADLESS_ATTACHED_CONTEXT_FORBIDDEN')
        code = mxd_error(mxd_path)
        if code:
            return rejected(mode, code)
        result = services.inspect_mxd(mxd_path=mxd_path)
        return {'ok': result.get('ok', False), 'requested_mode': mode,
                'execution_lane': 'headless',
                'target': {'kind': 'disk_mxd', 'path': mxd_path}, 'data': result}
    payload = {} if expected_context is None else {'_expected_context': expected_context}
    result = services.call('inspect_current_map', 'read', **payload)
    return {
        'ok': result.get('ok', False),
        'requested_mode': mode,
        'execution_lane': 'attached',
        'target': {'kind': 'CURRENT', 'context': result.get('context')},
        'data': result,
    }
