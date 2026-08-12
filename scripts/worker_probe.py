import json, os, time, threading
from internal.live_subnets import _cache_path, live_data_freshness, _sync_once
from internal.run_mode import background_on_web, is_worker_mode, inline_worker_expected
print('RUN_MODE=', os.environ.get('RUN_MODE'))
print('FETCH_MODE=', os.environ.get('LIVE_SUBNETS_FETCH_MODE'))
print('INLINE_WORKER=', os.environ.get('INLINE_WORKER'))
print('inline_worker_expected=', inline_worker_expected())
print('background_on_web=', background_on_web())
print('is_worker_mode=', is_worker_mode())
threads = [(t.name, t.daemon, t.is_alive()) for t in threading.enumerate()]
print('threads=', json.dumps(threads, default=str))
print('cache_path=', _cache_path())
print('exists=', os.path.isfile(_cache_path()))
fresh = live_data_freshness()
print('freshness=', json.dumps({k: fresh.get(k) for k in ('subnet_count','last_sync','stale','boot_status','rpc_healthy','effective_source')}, default=str))
try:
    from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state
    print('resolver_scheduler=', json.dumps(get_prediction_resolver_scheduler_state(), default=str))
except Exception as e:
    print('resolver_scheduler_error=', repr(e))
try:
    from internal.worker_heartbeat import is_alive, read_heartbeat
    print('heartbeat_alive=', is_alive(max_age_seconds=120))
    print('heartbeat=', json.dumps(read_heartbeat(), default=str))
except Exception as e:
    print('heartbeat_error=', repr(e))
t0=time.time()
ok = _sync_once()
print('sync_once=', ok, 'sec=', round(time.time()-t0, 1))