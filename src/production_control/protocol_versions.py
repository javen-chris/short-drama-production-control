"""Content-addressed protocol snapshots and impact-scoped RUN drift reports.

Snapshots are evidence, never automatic approval of changed rules. Legacy hashes
without archived bytes remain unknown; no current text is labelled historical.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


def snapshot(root: Path, manifest: dict) -> None:
    store = root / '.protocol_versions'
    objects = store / 'objects'
    objects.mkdir(parents=True, exist_ok=True)
    for entry in manifest['files']:
        data = (root / entry['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('PROTOCOL_CHANGED_DURING_SNAPSHOT: ' + entry['path'])
        target = objects / entry['sha256']
        if target.exists() and target.read_bytes() != data:
            raise ValueError('PROTOCOL_SNAPSHOT_CORRUPT: ' + str(target))
        if not target.exists():
            target.write_bytes(data)
    target = store / (manifest['fingerprint'] + '.json')
    if not target.exists():
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


def scoped_paths(contract: dict, *, current_only: bool = True) -> set[str]:
    from . import protocol_fingerprint
    REQUIRED_CORE_FILES = protocol_fingerprint.REQUIRED_CORE_FILES
    TARGET_MODE_PROTOCOL_FILES = protocol_fingerprint.TARGET_MODE_PROTOCOL_FILES
    current = next((s for s in contract.get('steps', []) if s.get('id') == contract.get('current_step_id')), {})
    gate = set(current.get('gate', []))
    steps = [s for s in contract.get('steps', []) if s.get('applicable')
             and (not current_only or gate.intersection(s.get('gate', [])))]
    paths = set(REQUIRED_CORE_FILES) | set(protocol_fingerprint.runtime_control_files(contract.get("protocol_root")))
    if contract.get('target_mode'):
        paths.update(TARGET_MODE_PROTOCOL_FILES)
    paths.update(r['path'] for s in steps for r in s.get('protocol_refs', []))
    return paths


def pinned_hashes(contract: dict, root: Path) -> dict[str, str]:
    hashes = dict(contract.get('protocol_snapshot_hashes', {}))
    archive = root / '.protocol_versions' / (str(contract.get('protocol_manifest_fingerprint', '')) + '.json')
    if archive.is_file():
        old = json.loads(archive.read_text(encoding='utf-8'))
        hashes = {e['path']: e['sha256'] for e in old['files']} | hashes
    for step in contract.get('steps', []):
        for ref in step.get('protocol_refs', []):
            hashes.setdefault(ref['path'], ref['sha256'])
    return hashes


def impact_report(contract: dict, root: Path, manifest: dict) -> dict:
    old_hashes = pinned_hashes(contract, root)
    current_scope = scoped_paths(contract)
    all_scope = scoped_paths(contract, current_only=False)
    changes = []
    for entry in manifest['files']:
        rel, new_hash = entry['path'], entry['sha256']
        old_hash = old_hashes.get(rel)
        if old_hash == new_hash:
            continue
        old_object = root / '.protocol_versions' / 'objects' / str(old_hash)
        new_text = (root / rel).read_text(encoding='utf-8', errors='replace')
        old_text = old_object.read_text(encoding='utf-8', errors='replace') if old_object.is_file() else None
        diff = ''.join(difflib.unified_diff(
            (old_text or '').splitlines(True), new_text.splitlines(True),
            fromfile=rel + '@' + str(old_hash or 'UNKNOWN'), tofile=rel + '@' + new_hash))
        changes.append({'path': rel, 'old_sha256': old_hash, 'new_sha256': new_hash,
                        'historical_text_available': old_text is not None,
                        'scope': 'current' if rel in current_scope else ('later' if rel in all_scope else 'unrelated'),
                        'diff': diff})
    return {'from_fingerprint': contract.get('protocol_manifest_fingerprint'),
            'to_fingerprint': manifest['fingerprint'], 'changes': changes,
            'confirmation_required_paths': sorted(c['path'] for c in changes if c['scope'] != 'unrelated')}


def check_current(contract: dict) -> list[str]:
    root = Path(contract['protocol_root'])
    hashes = pinned_hashes(contract, root)
    errors = []
    for rel in sorted(scoped_paths(contract)):
        target = root / rel
        if not target.is_file():
            errors.append(rel + ': applicable protocol missing')
        elif rel not in hashes:
            # Legacy manifests might have no text snapshots. Use only their
            # recorded hashes, never invent an old hash from live bytes.
            manifest = json.loads((root / 'protocol_manifest.json').read_text(encoding='utf-8'))
            expected = next((e['sha256'] for e in manifest['files'] if e['path'] == rel), None)
            if manifest['fingerprint'] != contract.get('protocol_manifest_fingerprint') or expected is None:
                errors.append(rel + ': historical hash unavailable; explicit scoped migration required')
            elif hashlib.sha256(target.read_bytes()).hexdigest() != expected:
                errors.append(rel + ': applicable protocol changed; inspect migration diff')
        elif hashlib.sha256(target.read_bytes()).hexdigest() != hashes[rel]:
            errors.append(rel + ': applicable protocol changed; inspect migration diff')
    return errors
