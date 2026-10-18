"""Checkpointed file batch copy; per-file atomic publication and verified replay."""
from pathlib import Path
import os
import hashlib
from app.core import fsops
from app.core.execution import WORK, canonical, overlap


def copy_batch_between_profiles(source_profile: str, paths: list[str],
                                destination_profile: str, destination_dir: str,
                                overwrite: bool = False,
                                flatten: bool = False,
                                preserve_relative_path: bool = True):
    if not paths or len(paths) > 10000:
        raise ValueError('Provide 1..10000 relative file paths')
    engine, meta, cancel = WORK.get()
    sp = engine.bind(meta['session_id'], source_profile)
    dp = engine.bind(meta['session_id'], destination_profile)
    fsops.require_write(dp)
    dest = fsops.resolve(destination_dir, dp)
    flatten_output = bool(flatten) or not bool(preserve_relative_path)
    copy_mode = 'flatten' if flatten_output else 'preserve-relative-path'
    sources = []
    seen = set()
    for raw in paths:
        relative = Path(raw)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Batch paths must be relative without traversal')
        destination_relative = Path(relative.name) if flatten_output else relative
        src, target = fsops.resolve(raw, sp), fsops.resolve(str(dest / destination_relative), dp)
        fsops.guard_secret(src)
        fsops.guard_secret(target)
        if not src.is_file():
            raise ValueError('Batch supports regular files only')
        key = canonical(target)
        if key in seen:
            raise ValueError('Duplicate destination')
        seen.add(key)
        sources.append((raw, src, target))
    if any(overlap(canonical(s), canonical(t)) for _,s,_ in sources for _,_,t in sources):
        raise ValueError('Source and destination must not overlap')
    opid = meta['operation_id']
    checkpoint = engine.journal.get(opid, meta['session_id'])['checkpoint'] or {}
    previous_mode = checkpoint.get('copy_mode')
    if previous_mode and previous_mode != copy_mode:
        raise ValueError('Batch copy mode changed since checkpoint; start a new operation')
    checkpoint['copy_mode'] = copy_mode
    checkpoint['flatten'] = flatten_output
    checkpoint['preserve_relative_path'] = not flatten_output
    manifest = checkpoint.setdefault('manifest', {})
    checkpoint['total_files'] = len(sources)
    checkpoint.setdefault('completed_files', 0)
    checkpoint.setdefault('bytes_copied', 0)
    for raw, src, target in sources:
        if cancel.is_set():
            raise InterruptedError('Batch cancelled at file boundary')
        # Revalidate approvals and resolution for every file boundary.
        if engine.bind(meta['session_id'], source_profile) != sp or engine.bind(meta['session_id'], destination_profile) != dp:
            raise PermissionError('Profile changed during copy')
        fsops.resolve(str(src), sp)
        fsops.resolve(str(target), dp)
        digest = fsops.sha256_file(src)
        previous = manifest.get(raw)
        if previous:
            if previous['sha256'] != digest:
                raise ValueError('Source changed since checkpoint')
            if target.is_file() and fsops.sha256_file(target) == digest:
                if previous['state'] != 'completed':
                    previous['state'] = 'completed'
                    checkpoint['completed_files'] += 1
                    checkpoint['bytes_copied'] += previous['size']
                    engine.journal.update(opid, checkpoint=checkpoint)
                continue
            if target.exists() or previous['state'] == 'completed':
                raise ValueError('Checkpoint destination changed; inspect before reconciliation')
        elif target.exists() and not overwrite:
            raise FileExistsError(str(target))
        if target.exists() and not previous:
            fsops.backup(target, reason='pre_batch_copy', profile=dp)
        manifest[raw] = {'sha256': digest, 'size': src.stat().st_size, 'state': 'prepared'}
        engine.journal.update(opid, checkpoint=checkpoint)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.parent / ('.zagent-' + opid + '-' + hashlib.sha256(raw.encode()).hexdigest()[:16] + '.part')
        try:
            with src.open('rb') as inp, temp.open('wb') as out:
                while True:
                    if cancel.is_set():
                        raise InterruptedError('Batch cancelled during file copy')
                    chunk = inp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if fsops.sha256_file(temp) != digest or fsops.sha256_file(src) != digest:
                raise IOError('Source changed during copy')
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()
        manifest[raw]['state'] = 'completed'
        checkpoint['completed_files'] += 1
        checkpoint['bytes_copied'] += manifest[raw]['size']
        engine.journal.update(opid, checkpoint=checkpoint)
    return {'verified': True, **checkpoint}
