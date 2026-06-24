# Exclude top ~40 subnets by total_stake (threshold: 400,000 TAO)
STAKE_THRESHOLD_TAO = float(os.environ.get("STAKE_THRESHOLD_TAO", "400000"))