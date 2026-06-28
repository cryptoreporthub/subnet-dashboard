

@app.get("/api/top-pick/hour")
def api_top_pick_hour():
    """Return the top pick for the current hour."""
    hour_picks = score_subnet_for_hour()
    return {"picks": hour_picks}

@app.get("/api/top-pick/day")
def api_top_pick_day():
    """Return the top pick for the current day."""
    day_picks = select_daily_pick()
    return {"picks": day_picks}
