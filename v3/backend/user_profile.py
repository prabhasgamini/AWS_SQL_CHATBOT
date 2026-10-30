"""
The summary shown right after login. It is built here, in trusted code, from the signed-in
user's own records. The model then turns it into a friendly greeting, and if the model isn't
available the plain_greeting() text is used instead, so logging in never ends on an error.
"""

import access
import metrics


def _try(metric, identifier, user):
    """A metric result, or None if it can't be calculated for this person."""
    try:
        return metrics.compute_metric(metric, identifier, 7, user)
    except (metrics.MetricError, access.AccessDenied):
        return None


def build_profile(user):
    if user.is_admin:
        return _admin_profile(user)
    if user.consumer_type == "HT":
        return _ht_profile(user)
    return _consumer_profile(user)


def _ht_profile(user):
    conn = access.trusted_connection()
    try:
        row = conn.execute("SELECT * FROM ht_consumer_master WHERE CONS_NUMBER = ?",
                           (user.consumer_ref,)).fetchone()
    finally:
        conn.close()
    return {
        "role": "HT consumer", "name": row["NAME"], "consumer_number": row["CONS_NUMBER"],
        "category": row["CATEGORY"], "type_of_supply": row["TYPE_OF_SUPPLY"],
        "contract_demand_kva": row["CONTRACT_DEMAND"], "connected_load_kw": row["CONNECTED_LOAD"],
        "supply_voltage": row["SUPPLY_VOLTAGE"], "feeder_code": row["FEEDER_CODE"],
        "transformer_location": row["TRANS_LOCATION"],
        "note": "Only master data is held for HT consumers here, there are no meter readings.",
    }


def _consumer_profile(user):
    conn = access.trusted_connection()
    try:
        c = conn.execute(
            "SELECT c.NAME, c.SCNO, c.CATEGORY, c.PHASE, c.CONTRACTED_LOAD, c.CONNECTED_LOAD, "
            "c.BILLING_STATUS, c.FEEDER_NUM, d.DTR_STRUCTURE_CODE, d.DTR_LOCATION, d.CAPACITY, "
            "s.MTR_SNO, s.MTR_TYPE "
            "FROM lt_consumer_master c "
            "LEFT JOIN consumer_mapping m ON m.CONS_NO = c.SCNO "
            "LEFT JOIN dtr_master d ON d.DTR_STRUCTURE_CODE = m.DTR_STRUC_CODE "
            "LEFT JOIN smart_meters_install_m s ON s.UKSCNO = c.UKSCNO "
            "WHERE c.SCNO = ?", (user.consumer_ref,)).fetchone()
    finally:
        conn.close()

    profile = {
        "role": "LT consumer", "name": c["NAME"], "consumer_number": c["SCNO"],
        "category": c["CATEGORY"], "phase": c["PHASE"],
        "contracted_load_kw": c["CONTRACTED_LOAD"], "connected_load_kw": c["CONNECTED_LOAD"],
        "billing_status": c["BILLING_STATUS"], "feeder": c["FEEDER_NUM"],
        "transformer": {"code": c["DTR_STRUCTURE_CODE"], "location": c["DTR_LOCATION"],
                        "capacity_kva": c["CAPACITY"]},
        "meter": ({"type": "smart", "serial": c["MTR_SNO"], "model": c["MTR_TYPE"]} if c["MTR_SNO"]
                  else {"type": "non-smart (manual monthly readings)"}),
    }

    last_week = {}
    energy = _try("energy_consumption", "", user)
    if energy:
        last_week.update(energy["result"])
        last_week["period"] = energy["window"]
    pf = _try("power_factor", "", user)
    if pf:
        last_week["average_power_factor"] = pf["result"]["average_power_factor"]
        last_week["power_factor_rating"] = pf["result"]["rating"]
    util = _try("load_utilisation", "", user)
    if util:
        last_week["load_utilisation"] = util["headline"]
        last_week["load_assessment"] = util["assessment"]
    share = _try("consumption_share", "", user)
    if share:
        last_week["share_of_transformer_energy_percent"] = share["result"]["share_of_dtr_energy_percent"]
    profile["recent_usage"] = last_week
    return profile


def _admin_profile(user):
    conn = access.trusted_connection()
    try:
        count = lambda sql: conn.execute(sql).fetchone()[0]
        totals = {
            "dtrs": count("SELECT COUNT(*) FROM dtr_master"),
            "lt_consumers": count("SELECT COUNT(*) FROM lt_consumer_master"),
            "ht_consumers": count("SELECT COUNT(*) FROM ht_consumer_master"),
            "smart_meters": count("SELECT COUNT(*) FROM smart_meters_install_m"),
        }
        totals["non_smart_lt_consumers"] = totals["lt_consumers"] - totals["smart_meters"]
        dtrs = [r["DTR_STRUCTURE_CODE"] for r in conn.execute("SELECT DTR_STRUCTURE_CODE FROM dtr_master ORDER BY ID")]
        smart = [(r["SCNO"], r["NAME"]) for r in conn.execute(
            "SELECT c.SCNO, c.NAME FROM lt_consumer_master c "
            "JOIN smart_meters_install_m s ON s.UKSCNO = c.UKSCNO ORDER BY c.SCNO")]
    finally:
        conn.close()

    loading = []
    for code in dtrs:
        m = _try("load_utilisation", code, user)
        if m:
            loading.append({"dtr": code, "location": m["entity"]["location"],
                            "peak_loading_percent": m["result"]["peak_loading_percent"],
                            "rating": m["result"]["rating"]})

    poor_pf, over_contract = [], []
    for scno, name in smart:
        pf = _try("power_factor", scno, user)
        if pf and pf["result"]["average_power_factor"] < 0.85:
            poor_pf.append({"name": name, "consumer_number": scno,
                            "average_power_factor": pf["result"]["average_power_factor"]})
        util = _try("load_utilisation", scno, user)
        if util and util["result"]["peak_utilisation_percent"] > 100:
            over_contract.append({"name": name, "consumer_number": scno,
                                  "peak_utilisation_percent": util["result"]["peak_utilisation_percent"]})

    return {
        "role": "administrator", "name": user.display_name, "totals": totals,
        "dtr_peak_loading_last_7_days": loading,
        "attention": {
            "dtrs_overloaded_or_heavily_loaded": [d for d in loading if d["peak_loading_percent"] >= 80],
            "consumers_with_poor_power_factor_below_0_85": poor_pf,
            "consumers_above_contracted_load": over_contract,
        },
    }


def plain_greeting(profile):
    """Fixed-text greeting for when the language model can't be reached."""
    name = profile["name"]
    if profile["role"] == "administrator":
        t = profile["totals"]
        att = profile["attention"]
        text = (f"Welcome, {name}. The database has {t['dtrs']} DTRs, {t['lt_consumers']} LT consumers "
                f"({t['smart_meters']} with smart meters) and {t['ht_consumers']} HT plants.")
        flags = []
        if att["dtrs_overloaded_or_heavily_loaded"]:
            flags.append("DTRs at 80% or more of capacity: " + ", ".join(
                f"{d['dtr']} ({d['peak_loading_percent']}%)" for d in att["dtrs_overloaded_or_heavily_loaded"]))
        if att["consumers_with_poor_power_factor_below_0_85"]:
            flags.append("poor power factor: " + ", ".join(
                f"{p['name']} ({p['average_power_factor']})" for p in att["consumers_with_poor_power_factor_below_0_85"]))
        if att["consumers_above_contracted_load"]:
            flags.append("above contracted load: " + ", ".join(
                f"{p['name']} ({p['peak_utilisation_percent']}%)" for p in att["consumers_above_contracted_load"]))
        return text + (" Needs attention: " + "; ".join(flags) + "." if flags else "") + \
            " Ask me about any consumer by name or number."

    if profile["role"] == "HT consumer":
        return (f"Welcome, {name} (consumer {profile['consumer_number']}). Contract demand "
                f"{profile['contract_demand_kva']} kVA, supply {profile['type_of_supply']}.")

    usage = profile.get("recent_usage", {})
    text = (f"Welcome, {name} (consumer {profile['consumer_number']}). You are a {profile['category'].lower()} "
            f"{profile['phase']} consumer with a contracted load of {profile['contracted_load_kw']} kW, "
            f"supplied from {profile['transformer']['code']} ({profile['transformer']['location']}).")
    if "total_kwh" in usage:
        text += f" Over the last {usage['period']['days']} days you used {usage['total_kwh']} kWh"
        if "average_power_factor" in usage:
            text += f" at a power factor of {usage['average_power_factor']} ({usage['power_factor_rating']})"
        text += "."
    elif "latest_period_units_kwh" in usage:
        text += f" Your latest billing period shows {usage['latest_period_units_kwh']} kWh."
    return text
