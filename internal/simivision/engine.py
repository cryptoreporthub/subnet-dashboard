# Add stake threshold for low-mid cap filtering
STAKE_THRESHOLD_TAO = float(os.environ.get("STAKE_THRESHOLD_TAO", "400000"))

def _filter_low_mid_cap_subnets(
    registry: Dict[str, Any], stake_threshold_tao: float = STAKE_THRESHOLD_TAO
) -> Dict[str, Any]:
    """
    Filter registry to only include low-mid cap subnets.
    Excludes subnets with total_stake >= threshold (default: 400,000 TAO).
    """
    filtered = {}
    for sid_str, data in registry.items():
        try:
            stake = data.get("staking_data", {}).get("total_stake", 0)
            if stake < stake_threshold_tao:
                filtered[sid_str] = data
        except (ValueError, TypeError):
            filtered[sid_str] = data
    return filtered