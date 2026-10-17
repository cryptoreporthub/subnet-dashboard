"""Build scripts/prototypes/fixtures/scores_2026-10-17.json (price history = committed Aug cache, so technicals are stale/partial): day score of every subnet in the committed prod cross-section,
computed by the product's own score_subnet_for_day (read-only import; telegram rows pre-supplied empty so it takes ms).
Only needed to regenerate the fixture:
  /home/user/subnet-dashboard/.venv/bin/python scripts/prototypes/make_fixtures.py
"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
work = tempfile.mkdtemp(prefix="fixtures_")
os.makedirs(os.path.join(work, "data")); shutil.copytree(os.path.join(REPO, "config"), os.path.join(work, "config"))
# the committed price_cache.json (Jul31-Aug14, STALE vs the Oct-17 cross-section) gives the technical expert real candles for the names it covers;
# without it technical is exactly 0.5 for every name. Names absent from the cache still get neutral technicals.
shutil.copy(os.path.join(REPO, "data", "price_cache.json"), os.path.join(work, "data", "price_cache.json"))
os.chdir(work)
from internal.council import state_vector as sv

subs = [s for s in json.load(open(os.path.join(HERE, "fixtures", "subnets_2026-10-17.json")))["subnets"] if s.get("netuid") not in (0, None)]
out = {}
for s in subs:
    r = sv.score_subnet_for_day(s, {"telegram_conviction_rows": []})
    out[str(s["netuid"])] = {"score": r["total_score"], "confidence": r["confidence"], "marketcap_rank": s.get("marketcap_rank"),
                             "emission": s.get("emission"), "volume": s.get("volume"), "market_cap": s.get("market_cap"),
                             "price_change_24h": s.get("price_change_24h"), "price_change_7d": s.get("price_change_7d"), "name": s.get("name"),
                             "experts": {k: v for k, v in r["expert_contributions"].items() if k in ("quant", "hype", "dark_horse", "technical")}}
json.dump(out, open(os.path.join(HERE, "fixtures", "scores_2026-10-17.json"), "w"))
print(len(out), "subnets scored")
shutil.rmtree(work, ignore_errors=True)
