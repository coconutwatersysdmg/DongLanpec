"""Version guards for hand-reviewed semantic labels and exact row joins."""
import hashlib
import json


def dependency_fingerprint(traces, path, function):
    entries = traces if isinstance(traces, dict) else {(f['path'], f['name']): f for f in traces}
    key = (path, function)
    if key not in entries:
        return ''
    reached, frontier = {key}, {key}
    for _ in range(4):
        children = {tuple(target) for k in frontier for step in entries[k]['steps']
                    for call in step['calls'] for target in call.get('resolved', []) if tuple(target) in entries}
        frontier = children - reached
        reached.update(frontier)
    payload = [(p, f, entries[(p, f)]['fingerprint']) for p, f in sorted(reached)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
