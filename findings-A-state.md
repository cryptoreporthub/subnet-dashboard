# Workstream A — State Layer & Concurrency (commit 44fd2fb7)

## A1 — Atomic write pattern: CONFIRMED
tempfile+os.replace atomic writes throughout internal/ (grep "os.replace|tempfile"): internal/council/daily_pick_engine.py:49; resolver_scheduler.py:116-120; score_snapshots.py:115; pick_score_cache.py:98; resolver.py:166; price_reference.py:142-486 (os.fdopen+os.replace); +8 more.
A1b direct open(...,'w'): CORRECTED — initial single-quote grep returned zero; corrected grep found ~15 sites but ALL write to tmp then rename (e.g. daily_pick_engine.py:47 open(tmp,"w") -> :49 os.replace). EXCEPTION: internal/worker_heartbeat.py:29 `open(path,"w")` writes data/.worker_heartbeat directly (non-atomic truncate-in-place; reader can see partial/empty file).

## A2 — SQLite access: CONFIRMED
internal/fetchers/_sqlite.py:29 PRAGMA journal_mode=WAL; connect(timeout=10, check_same_thread=False); per-path threading.Lock + db_conn ctx mgr. internal/store/db.py:13-14 delegates. VOLUME_DB_PATH=data/volume_cache.db (internal/council/chain_client.py:36). Web+worker share WAL DB; busy timeout via connect(timeout=10).

## A3 — File locking: PARTIAL
flock ONLY in internal/council/pick_score_cache.py:104 (LOCK_EX) / :108 (LOCK_UN). No general inter-process lock on shared JSON; atomic rename (A1) is the only protection. worker_heartbeat.py has no lock.
