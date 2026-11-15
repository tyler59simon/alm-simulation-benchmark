"""Private Living Memory stores: bootstrap, CLI access and export/import handover. Never touches the real store."""
import json
from pathlib import Path

from . import clock
from .common import clean_env, config, run_cmd, write_json


def lm(store, args, payload=None, actor=None, cwd=None):
    """Run the installed Living Memory CLI against one store; returns parsed JSON (or raw text)."""
    cfg = config()
    extra = {**clock.lm_env(), 'LIVING_MEMORY_ROOT': str(store)}   # the simulated time of the phase, when the run has a clock
    if actor:
        extra['LIVING_MEMORY_ACTOR'] = actor
    r = run_cmd([cfg['python'], cfg['lm_cli']] + list(args), cwd=cwd or store, env=clean_env(extra),
                input=json.dumps(payload) if payload is not None else None, timeout=120)
    out = (r.stdout or '').strip()
    try:
        value = json.loads(out.splitlines()[-1]) if out else {}
    except (ValueError, IndexError):
        value = {'raw': out}
    if r.returncode:
        raise RuntimeError(f'living_memory {" ".join(map(str, args[:3]))} failed: {(r.stderr or out)[-800:]}')
    return value


def _apply(store, plan, domain=None):
    args = (['--domain', domain] if domain else []) + ['apply', plan['plan_id'], '--expected-plan-sha256', plan['digest']]
    return lm(store, args)


def assert_not_real(store):
    real = config().get('real_store')
    if real and Path(store).resolve() == Path(real).resolve():
        raise SystemExit(f'Refusing to use the real Living Memory store {real}')


def bootstrap(store, domain, bind_paths, taxonomy_extra=()):
    """Fresh store: bind domain to each path, run the schema migration, extend the taxonomy, mark as sandbox."""
    store = Path(store)
    assert_not_real(store)
    store.mkdir(parents=True, exist_ok=True)
    for p in bind_paths:
        Path(p).mkdir(parents=True, exist_ok=True)
        lm(store, ['bind', domain, str(p)])
    _apply(store, lm(store, ['migration-plan']))
    write_json(store / 'sandbox.json', {'sandbox': True})
    extra = [t for t in taxonomy_extra if t not in (json.loads((store / 'tag_taxonomy.json').read_text(encoding='utf-8')).get('tags') or [])]
    if extra:
        _apply(store, lm(store, ['taxonomy-plan'] + extra))
    return lm(store, ['doctor'])


def bind(store, domain, path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return lm(store, ['bind', domain, str(path)])


def handover(src_store, dst_store, domain, bundle):
    """IT handover: export the leaver's domain and import it into the joiner's store through a reviewed plan."""
    bundle = Path(bundle)
    bundle.parent.mkdir(parents=True, exist_ok=True)
    if bundle.exists():
        bundle.unlink()
    try:
        exported = lm(src_store, ['--domain', domain, 'export', '--out', str(bundle)])
    except RuntimeError as e:
        if 'No notes match' in str(e):   # the leaver saved nothing: there is nothing to hand over
            return {'skipped': 'leaver store has no notes'}
        raise
    plan = lm(dst_store, ['--domain', domain, 'import-plan', str(bundle)])
    applied = _apply(dst_store, plan, domain) if plan.get('plan_id') else {'skipped': 'no plan', 'plan': plan}
    return {'export': exported, 'plan': {k: plan.get(k) for k in ('plan_id', 'summary', 'counts', 'conflicts') if k in plan},
            'apply': applied}
