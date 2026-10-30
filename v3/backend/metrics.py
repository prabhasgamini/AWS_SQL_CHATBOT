"""
The numbers the model shouldn't work out in its head: power factor, energy, load utilisation,
share of the transformer. All maths happens here in Python, and every result carries the formula
and the inputs so the answer can be checked.

Access rules are enforced in this file too (not left to the model):
  * admins can ask about any consumer, plant or DTR, by number or by name
  * a consumer can only ask about themselves; anything else raises AccessDenied

The time window ends at the LATEST reading of the meter involved (not at "now"), so the
figures still work when the sample database is a few days old.
"""

import math
import re
from datetime import datetime, timedelta

import access
import config
from database import INTERVAL_HOURS

TS_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_DAYS = 30
SELF_WORDS = {"", "me", "my", "myself", "self", "mine", "i"}


class MetricError(Exception):
    """Something can't be calculated. The message says why and is safe to show."""


# ---------------------------------------------------------------------------
# Finding who or what the question is about
# ---------------------------------------------------------------------------

def _tokens(text):
    return set(re.findall(r"[a-z]+", (text or "").lower()))


def _is_self(ident, user):
    low = ident.strip().lower()
    if low in SELF_WORDS:
        return True
    own = {str(v).lower() for v in (user.consumer_ref, user.ukscno, user.dtr_code, user.display_name) if v}
    if low in own:
        return True
    words = _tokens(low)
    return bool(words) and words <= _tokens(user.display_name)


_LT_SQL = (
    "SELECT c.ID, c.SCNO, c.UKSCNO, c.NAME, c.CATEGORY, c.PHASE, c.CONTRACTED_LOAD, c.CONNECTED_LOAD, "
    "m.DTR_STRUC_CODE, s.MTR_SNO "
    "FROM lt_consumer_master c "
    "LEFT JOIN consumer_mapping m ON m.CONS_NO = c.SCNO "
    "LEFT JOIN smart_meters_install_m s ON s.UKSCNO = c.UKSCNO "
)


def _lt_entity(row):
    return {"type": "LT", "id": row["ID"], "scno": row["SCNO"], "ukscno": row["UKSCNO"],
            "name": row["NAME"], "category": row["CATEGORY"], "phase": row["PHASE"],
            "contracted_kw": row["CONTRACTED_LOAD"], "connected_kw": row["CONNECTED_LOAD"],
            "dtr_code": row["DTR_STRUC_CODE"], "meter_sno": row["MTR_SNO"]}


def _dtr_entity(conn, code):
    row = conn.execute(
        "SELECT d.DTR_STRUCTURE_CODE, d.DTR_LOCATION, d.CAPACITY, f.NEW_MTR_MSN, f.NEW_MTR_MF "
        "FROM dtr_master d LEFT JOIN fdr_dtr_newcharge f ON f.DTR_ID = d.DTR_STRUCTURE_CODE "
        "WHERE d.DTR_STRUCTURE_CODE = ?", (code,)).fetchone()
    if row is None:
        raise MetricError(f"There is no DTR with code {code}.")
    return {"type": "DTR", "code": row["DTR_STRUCTURE_CODE"], "location": row["DTR_LOCATION"],
            "capacity_kva": row["CAPACITY"], "meter_msn": row["NEW_MTR_MSN"],
            "mf": row["NEW_MTR_MF"] or 1.0}


def resolve_entity(conn, identifier, user):
    """Turn a number, DTR code or name into a consumer / DTR / plant record."""
    ident = (identifier or "").strip()

    if not user.is_admin:
        if re.fullmatch(r"(?i)dtr[\s_-]*\d+", ident):
            raise access.AccessDenied("Transformer-level figures are available to administrators only.")
        if not _is_self(ident, user):
            raise access.AccessDenied("You can only see figures for your own connection.")
        ident = user.consumer_ref
    if not ident:
        raise MetricError("Which consumer, DTR or plant? Give a consumer number or a name.")

    dtr = re.fullmatch(r"(?i)dtr[\s_-]*(\d+)", ident)
    if dtr:
        return _dtr_entity(conn, f"DTR-{dtr.group(1)}")

    row = conn.execute(_LT_SQL + "WHERE c.SCNO = ? OR c.UKSCNO = ?", (ident, ident)).fetchone()
    if row:
        return _lt_entity(row)

    ht = conn.execute("SELECT * FROM ht_consumer_master WHERE CONS_NUMBER = ?", (ident,)).fetchone()
    if ht:
        return _ht_entity(ht)

    # by name: exact (ignoring case) first, then anything containing it
    low = ident.lower()
    lt_rows = conn.execute(_LT_SQL + "WHERE lower(c.NAME) = ?", (low,)).fetchall()
    ht_rows = conn.execute("SELECT * FROM ht_consumer_master WHERE lower(NAME) = ?", (low,)).fetchall()
    if not lt_rows and not ht_rows:
        lt_rows = conn.execute(_LT_SQL + "WHERE lower(c.NAME) LIKE ?", (f"%{low}%",)).fetchall()
        ht_rows = conn.execute("SELECT * FROM ht_consumer_master WHERE lower(NAME) LIKE ?",
                               (f"%{low}%",)).fetchall()

    found = [("LT", r) for r in lt_rows] + [("HT", r) for r in ht_rows]
    if not found:
        raise MetricError(f"No consumer, plant or DTR matches '{ident}'.")
    if len(found) > 1:
        options = ", ".join(
            f"{r['NAME']} ({r['SCNO'] if kind == 'LT' else r['CONS_NUMBER']})" for kind, r in found[:8])
        raise MetricError(f"Several match '{ident}': {options}. Which one do you mean? "
                          "Use the consumer number to be exact.")
    kind, row = found[0]
    return _lt_entity(row) if kind == "LT" else _ht_entity(row)


def _ht_entity(row):
    return {"type": "HT", "number": row["CONS_NUMBER"], "name": row["NAME"],
            "contract_demand_kva": row["CONTRACT_DEMAND"], "connected_kw": row["CONNECTED_LOAD"]}


def _brief(entity):
    if entity["type"] == "LT":
        return {"type": "LT consumer", "name": entity["name"], "consumer_number": entity["scno"],
                "category": entity["category"], "phase": entity["phase"]}
    if entity["type"] == "DTR":
        return {"type": "DTR", "code": entity["code"], "location": entity["location"],
                "capacity_kva": entity["capacity_kva"]}
    return {"type": "HT consumer", "name": entity["name"], "consumer_number": entity["number"]}


# ---------------------------------------------------------------------------
# Reading the interval data
# ---------------------------------------------------------------------------

def _load_series(conn, table, msn, days, end=None):
    """Interval rows (ts, vah_imp, wh_imp) for the last `days` days ending at the latest reading."""
    if end is None:
        end = conn.execute(f"SELECT MAX(ts) FROM {table} WHERE msn = ?", (msn,)).fetchone()[0]
    if end is None:
        return []
    start = datetime.strptime(end, TS_FORMAT) - timedelta(days=days)
    return conn.execute(
        f"SELECT ts, vah_imp, wh_imp FROM {table} WHERE msn = ? AND ts > ? AND ts <= ? ORDER BY ts",
        (msn, start.strftime(TS_FORMAT), end)).fetchall()


def _series_source(entity):
    """(table, msn, multiplication factor) for the meter behind this entity, or None."""
    if entity["type"] == "DTR":
        return ("t_nw_blp", entity["meter_msn"], entity["mf"]) if entity["meter_msn"] else None
    if entity["type"] == "LT" and entity["meter_sno"]:
        table = "t_blp_sp" if "1" in (entity["phase"] or "") else "t_blp_tp"
        return table, entity["meter_sno"], 1.0
    return None


def _stats(rows, mf=1.0):
    vah = sum(r["vah_imp"] for r in rows) * mf
    wh = sum(r["wh_imp"] for r in rows) * mf
    hours = len(rows) * INTERVAL_HOURS
    kwh, kvah = wh / 1000, vah / 1000
    peak_kva_row = max(rows, key=lambda r: r["vah_imp"])
    peak_kw_row = max(rows, key=lambda r: r["wh_imp"])
    interval_pf = [r["wh_imp"] / r["vah_imp"] for r in rows if r["vah_imp"]]
    return {
        "kwh": kwh, "kvah": kvah, "hours": hours,
        "avg_kw": kwh / hours, "avg_kva": kvah / hours,
        "peak_kva": peak_kva_row["vah_imp"] * mf / 1000 / INTERVAL_HOURS, "peak_kva_at": peak_kva_row["ts"],
        "peak_kw": peak_kw_row["wh_imp"] * mf / 1000 / INTERVAL_HOURS, "peak_kw_at": peak_kw_row["ts"],
        "pf": wh / vah if vah else None,
        "pf_min": min(interval_pf), "pf_max": max(interval_pf),
        "pct_below_090": 100 * sum(1 for p in interval_pf if p < 0.90) / len(interval_pf),
    }


def _window(rows):
    return {"from": rows[0]["ts"], "to": rows[-1]["ts"], "intervals": len(rows),
            "days": round(len(rows) * INTERVAL_HOURS / 24, 2)}


def _rows_for(conn, entity, days):
    source = _series_source(entity)
    if source is None:
        raise MetricError(_no_interval_message(entity))
    table, msn, mf = source
    rows = _load_series(conn, table, msn, days)
    if not rows:
        raise MetricError(f"There are no meter readings for {_label(entity)}.")
    return rows, mf


def _label(entity):
    return entity.get("name") or entity.get("code")


def _no_interval_message(entity):
    if entity["type"] == "HT":
        return (f"{entity['name']} is an HT plant. This database only holds master data for HT "
                f"consumers (contract demand {entity['contract_demand_kva']} kVA, connected load "
                f"{entity['connected_kw']} kW), with no meter readings, so this can't be calculated.")
    return (f"{entity['name']} has no smart meter, so there are no interval readings. "
            "Only monthly readings exist for this consumer, which can give total units but not power factor.")


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------

def _pf_rating(pf):
    if pf >= 0.95:
        return "excellent"
    if pf >= 0.90:
        return "good"
    if pf >= 0.85:
        return "acceptable"
    return "poor"


def _loading_rating(pct):
    if pct > 100:
        return "overloaded"
    if pct >= 80:
        return "heavily loaded"
    if pct >= 50:
        return "healthy"
    return "lightly loaded"


def _utilisation_rating(pct):
    if pct > 100:
        return "above the contracted load"
    if pct >= 80:
        return "close to the contracted load"
    return "within the contracted load"


def _r(value, digits=2):
    return None if value is None else round(value, digits)


# ---------------------------------------------------------------------------
# The metrics
# ---------------------------------------------------------------------------

def _power_factor(conn, entity, days, user):
    rows, mf = _rows_for(conn, entity, days)
    s = _stats(rows, mf)
    pf = s["pf"]

    kvar_avg = math.sqrt(max(s["avg_kva"] ** 2 - s["avg_kw"] ** 2, 0))
    result = {
        "average_power_factor": _r(pf, 3),
        "rating": _pf_rating(pf),
        "lowest_interval_power_factor": _r(s["pf_min"], 3),
        "highest_interval_power_factor": _r(s["pf_max"], 3),
        "intervals_below_0_90_percent": _r(s["pct_below_090"], 1),
        "average_reactive_power_kvar": _r(kvar_avg, 2),
    }
    notes = []
    if pf < 0.95:
        capacitor = s["avg_kw"] * (math.tan(math.acos(pf)) - math.tan(math.acos(0.95)))
        result["capacitor_kvar_to_reach_0_95"] = _r(capacitor, 1)
        notes.append("Capacitor size is indicative, worked out from the average demand.")
    if pf < 0.85:
        assessment = ("Poor power factor. Many utilities add a surcharge below about 0.85-0.90, "
                      "and power factor correction (capacitors) would usually pay off.")
    elif pf < 0.90:
        assessment = "Acceptable but on the low side, close to where surcharges usually begin."
    else:
        assessment = f"{_pf_rating(pf).capitalize()}. No power factor concern."
    return {
        "metric": "power_factor", "entity": _brief(entity), "window": _window(rows),
        "headline": f"Average power factor {pf:.3f} ({_pf_rating(pf)})",
        "result": result,
        "formula": "power factor = total active energy (kWh) / total apparent energy (kVAh)",
        "inputs": {"total_kwh": _r(s["kwh"]), "total_kvah": _r(s["kvah"])},
        "assessment": assessment, "notes": notes,
    }


def _energy(conn, entity, days, user):
    if entity["type"] == "LT" and not entity["meter_sno"]:
        return _energy_monthly(conn, entity)

    rows, mf = _rows_for(conn, entity, days)
    s = _stats(rows, mf)
    window = _window(rows)
    daily = s["kwh"] / (window["days"] or 1)
    result = {
        "total_kwh": _r(s["kwh"]), "total_kvah": _r(s["kvah"]),
        "daily_average_kwh": _r(daily),
        "average_demand_kw": _r(s["avg_kw"]),
        "peak_demand_kw": _r(s["peak_kw"]), "peak_demand_kw_at": s["peak_kw_at"],
        "peak_demand_kva": _r(s["peak_kva"]),
        "load_factor_percent": _r(100 * s["avg_kw"] / s["peak_kw"], 1),
    }
    return {
        "metric": "energy_consumption", "entity": _brief(entity), "window": window,
        "headline": f"{s['kwh']:.1f} kWh in {window['days']} days ({daily:.1f} kWh/day)",
        "result": result,
        "formula": ("kWh = sum of active energy (wh_imp) / 1000; load factor = average demand (kW) / "
                    "peak demand (kW) x 100; demand (kW) = interval Wh x 4 / 1000 (15 minute intervals)"),
        "inputs": {"intervals": window["intervals"], "meter_multiplication_factor": mf},
        "assessment": f"Load factor {result['load_factor_percent']}%: the closer to 100%, the flatter the usage.",
        "notes": [],
    }


def _monthly_periods(conn, cons_id, limit=6):
    rows = conn.execute(
        "SELECT PRESENT_READING, PREV_READING, PRESENT_MTRRDDATE, PREV_MTRRDDATE FROM lt_meter_data "
        "WHERE CONS_NUMBER = ? ORDER BY PRESENT_MTRRDDATE DESC LIMIT ?", (cons_id, limit)).fetchall()
    periods = []
    for r in rows:
        start = datetime.strptime(r["PREV_MTRRDDATE"], "%Y-%m-%d")
        end = datetime.strptime(r["PRESENT_MTRRDDATE"], "%Y-%m-%d")
        periods.append({"from": r["PREV_MTRRDDATE"], "to": r["PRESENT_MTRRDDATE"],
                        "days": max((end - start).days, 1),
                        "units_kwh": round(r["PRESENT_READING"] - r["PREV_READING"], 1)})
    return periods        # newest first


def _energy_monthly(conn, entity):
    periods = _monthly_periods(conn, entity["id"])
    if not periods:
        raise MetricError(f"There are no meter readings for {entity['name']}.")
    latest = periods[0]
    average = sum(p["units_kwh"] for p in periods) / len(periods)
    result = {
        "latest_period_units_kwh": latest["units_kwh"],
        "latest_period_daily_average_kwh": _r(latest["units_kwh"] / latest["days"]),
        "average_units_per_period_kwh": _r(average, 1),
    }
    notes = ["Non-smart meter: based on monthly manual readings. The register is assumed to be in kWh."]
    assessment = f"{latest['units_kwh']} kWh over {latest['days']} days."
    if len(periods) > 1 and periods[1]["units_kwh"]:
        change = 100 * (latest["units_kwh"] - periods[1]["units_kwh"]) / periods[1]["units_kwh"]
        result["change_vs_previous_period_percent"] = _r(change, 1)
        assessment += f" That is {change:+.1f}% compared with the previous period."
    return {
        "metric": "energy_consumption", "entity": _brief(entity),
        "window": {"from": latest["from"], "to": latest["to"], "days": latest["days"], "intervals": None},
        "headline": f"{latest['units_kwh']} kWh in the latest billing period",
        "result": result,
        "formula": "units = present reading - previous reading; change % = (latest - previous) / previous x 100",
        "inputs": {"periods_newest_first": periods},
        "assessment": assessment, "notes": notes,
    }


def _utilisation(conn, entity, days, user):
    if entity["type"] == "DTR":
        rows, mf = _rows_for(conn, entity, days)
        s = _stats(rows, mf)
        cap = entity["capacity_kva"]
        peak_pct, avg_pct = 100 * s["peak_kva"] / cap, 100 * s["avg_kva"] / cap
        return {
            "metric": "load_utilisation", "entity": _brief(entity), "window": _window(rows),
            "headline": f"Peak loading {peak_pct:.1f}% of capacity ({_loading_rating(peak_pct)})",
            "result": {"peak_loading_percent": _r(peak_pct, 1), "average_loading_percent": _r(avg_pct, 1),
                       "rating": _loading_rating(peak_pct), "peak_demand_kva": _r(s["peak_kva"]),
                       "peak_at": s["peak_kva_at"], "capacity_kva": cap},
            "formula": "loading % = demand (kVA) / transformer capacity (kVA) x 100",
            "inputs": {"peak_demand_kva": _r(s["peak_kva"]), "average_demand_kva": _r(s["avg_kva"]),
                       "capacity_kva": cap},
            "assessment": ("Over 100% means the transformer is overloaded at peak and at risk of "
                           "overheating or failure." if peak_pct > 100 else
                           f"The transformer is {_loading_rating(peak_pct)} at its busiest."),
            "notes": [],
        }

    contracted = entity["contracted_kw"]
    if not entity["meter_sno"]:
        periods = _monthly_periods(conn, entity["id"])
        if not periods:
            raise MetricError(f"There are no meter readings for {entity['name']}.")
        latest = periods[0]
        avg_kw = latest["units_kwh"] / (latest["days"] * 24)
        pct = 100 * avg_kw / contracted
        return {
            "metric": "load_utilisation", "entity": _brief(entity),
            "window": {"from": latest["from"], "to": latest["to"], "days": latest["days"], "intervals": None},
            "headline": f"Average load about {pct:.1f}% of contracted load (estimate)",
            "result": {"average_utilisation_percent": _r(pct, 1), "average_demand_kw": _r(avg_kw),
                       "contracted_load_kw": contracted},
            "formula": "average demand (kW) = units (kWh) / (days x 24); utilisation % = average demand / contracted load x 100",
            "inputs": {"units_kwh": latest["units_kwh"], "days": latest["days"], "contracted_load_kw": contracted},
            "assessment": "Only an average can be estimated without a smart meter, the real peak will be higher.",
            "notes": ["Non-smart meter: estimated from monthly readings (assumed kWh)."],
        }

    rows, mf = _rows_for(conn, entity, days)
    s = _stats(rows, mf)
    peak_pct, avg_pct = 100 * s["peak_kw"] / contracted, 100 * s["avg_kw"] / contracted
    rating = _utilisation_rating(peak_pct)
    assessment = f"Peak demand is {rating}."
    if peak_pct > 100:
        assessment = (f"Peak demand of {s['peak_kw']:.2f} kW exceeds the contracted load of {contracted} kW "
                      f"by {s['peak_kw'] - contracted:.2f} kW. Consider applying for a load enhancement.")
    return {
        "metric": "load_utilisation", "entity": _brief(entity), "window": _window(rows),
        "headline": f"Peak demand {peak_pct:.1f}% of contracted load ({rating})",
        "result": {"peak_utilisation_percent": _r(peak_pct, 1), "average_utilisation_percent": _r(avg_pct, 1),
                   "peak_demand_kw": _r(s["peak_kw"]), "peak_at": s["peak_kw_at"],
                   "contracted_load_kw": contracted, "connected_load_kw": entity["connected_kw"]},
        "formula": "utilisation % = demand (kW) / contracted load (kW) x 100",
        "inputs": {"peak_demand_kw": _r(s["peak_kw"]), "average_demand_kw": _r(s["avg_kw"]),
                   "contracted_load_kw": contracted},
        "assessment": assessment, "notes": [],
    }


def _dtr_window(conn, dtr_code, days):
    """The DTR meter's rows for the window, which other figures are compared against."""
    dtr = _dtr_entity(conn, dtr_code)
    if not dtr["meter_msn"]:
        raise MetricError(f"DTR {dtr_code} has no AMR meter in this database.")
    rows = _load_series(conn, "t_nw_blp", dtr["meter_msn"], days)
    if not rows:
        raise MetricError(f"There are no meter readings for DTR {dtr_code}.")
    return dtr, rows


def _smart_consumers_on(conn, dtr_code):
    return conn.execute(
        "SELECT c.SCNO, c.NAME, c.PHASE, s.MTR_SNO FROM consumer_mapping m "
        "JOIN lt_consumer_master c ON c.SCNO = m.CONS_NO "
        "JOIN smart_meters_install_m s ON s.UKSCNO = c.UKSCNO WHERE m.DTR_STRUC_CODE = ?",
        (dtr_code,)).fetchall()


def _kvah_between(conn, table, msn, first, last):
    total = conn.execute(f"SELECT SUM(vah_imp) FROM {table} WHERE msn = ? AND ts >= ? AND ts <= ?",
                         (msn, first, last)).fetchone()[0]
    return (total or 0) / 1000


def _share(conn, entity, days, user):
    if entity["type"] != "LT":
        raise MetricError("Share of the transformer is worked out for an individual LT consumer.")
    if not entity["dtr_code"]:
        raise MetricError(f"{entity['name']} isn't mapped to a DTR.")

    dtr, dtr_rows = _dtr_window(conn, entity["dtr_code"], days)
    window = _window(dtr_rows)
    dtr_kvah = sum(r["vah_imp"] for r in dtr_rows) * dtr["mf"] / 1000
    dtr_kwh = sum(r["wh_imp"] for r in dtr_rows) * dtr["mf"] / 1000
    notes = []

    source = _series_source(entity)
    if source:
        table, msn, _ = source
        rows = _load_series(conn, table, msn, days, end=window["to"])
        rows = [r for r in rows if r["ts"] >= window["from"]]
        if not rows:
            raise MetricError(f"There are no meter readings for {entity['name']} in that period.")
        kvah = sum(r["vah_imp"] for r in rows) / 1000
        kwh = sum(r["wh_imp"] for r in rows) / 1000
        method = "measured by the consumer's smart meter"
    else:
        periods = _monthly_periods(conn, entity["id"])
        if not periods:
            raise MetricError(f"There are no meter readings for {entity['name']}.")
        kwh = periods[0]["units_kwh"] / periods[0]["days"] * window["days"]    # kWh per day x days in window
        kvah = None
        method = "estimated from the latest monthly readings"
        notes.append("Non-smart meter: this share is an estimate, based on monthly readings (assumed kWh).")

    share_kwh = 100 * kwh / dtr_kwh
    result = {
        "share_of_dtr_energy_percent": _r(share_kwh, 2),
        "consumer_kwh": _r(kwh), "dtr_kwh": _r(dtr_kwh), "dtr_code": dtr["code"],
    }
    if kvah is not None:
        result["share_of_dtr_kvah_percent"] = _r(100 * kvah / dtr_kvah, 2)

    if user.is_admin:
        peers = []
        for p in _smart_consumers_on(conn, dtr["code"]):
            table = "t_blp_sp" if "1" in p["PHASE"] else "t_blp_tp"
            peers.append((p["SCNO"], _kvah_between(conn, table, p["MTR_SNO"], window["from"], window["to"])))
        peers.sort(key=lambda x: x[1], reverse=True)
        ranks = [scno for scno, _ in peers]
        if entity["scno"] in ranks:
            result["rank_among_smart_consumers_on_dtr"] = f"{ranks.index(entity['scno']) + 1} of {len(ranks)}"

    notes.append("The transformer total also covers consumers without smart meters and network losses, "
                 "so shares of all consumers add up to less than 100%.")
    return {
        "metric": "consumption_share", "entity": _brief(entity), "window": window,
        "headline": f"{share_kwh:.1f}% of the energy on {dtr['code']} ({method})",
        "result": result,
        "formula": "share % = consumer energy (kWh) / transformer meter energy (kWh) x 100",
        "inputs": {"consumer_kwh": _r(kwh), "dtr_kwh": _r(dtr_kwh)},
        "assessment": f"This consumer accounts for about {share_kwh:.1f}% of everything that passes through {dtr['code']}.",
        "notes": notes,
    }


def _top_consumers(conn, entity, days, user):
    if entity["type"] != "DTR":
        raise MetricError("Top consumers is worked out for a DTR. Give a DTR code such as DTR-1001.")
    dtr, dtr_rows = _dtr_window(conn, entity["code"], days)
    window = _window(dtr_rows)
    dtr_kvah = sum(r["vah_imp"] for r in dtr_rows) * dtr["mf"] / 1000

    ranking = []
    for p in _smart_consumers_on(conn, dtr["code"]):
        table = "t_blp_sp" if "1" in p["PHASE"] else "t_blp_tp"
        kvah = _kvah_between(conn, table, p["MTR_SNO"], window["from"], window["to"])
        ranking.append({"name": p["NAME"], "consumer_number": p["SCNO"], "kvah": _r(kvah),
                        "share_percent": _r(100 * kvah / dtr_kvah, 1)})
    ranking.sort(key=lambda r: r["kvah"], reverse=True)
    accounted = sum(r["share_percent"] for r in ranking)
    return {
        "metric": "top_consumers", "entity": _brief(entity), "window": window,
        "headline": f"{len(ranking)} smart-metered consumers on {dtr['code']}, highest first",
        "result": {"ranking": ranking, "transformer_kvah": _r(dtr_kvah),
                   "other_consumers_and_losses_percent": _r(100 - accounted, 1)},
        "formula": "share % = consumer apparent energy (kVAh) / transformer meter kVAh x 100",
        "inputs": {"transformer_kvah": _r(dtr_kvah)},
        "assessment": "The remainder is non-smart consumers plus network losses.", "notes": [],
    }


_HANDLERS = {
    "power_factor": _power_factor,
    "energy_consumption": _energy,
    "load_utilisation": _utilisation,
    "consumption_share": _share,
    "top_consumers": _top_consumers,
}


def normalise_metric(name):
    text = re.sub(r"[^a-z]+", " ", (name or "").lower()).strip()
    if "top" in text or "rank" in text or "biggest" in text or "highest consum" in text:
        return "top_consumers"
    if "share" in text or "percent" in text or "contribution" in text or "proportion" in text:
        return "consumption_share"
    if "power factor" in text or text in {"pf", "powerfactor"}:
        return "power_factor"
    if "util" in text or "loading" in text or "overload" in text or "contracted" in text:
        return "load_utilisation"
    if any(w in text for w in ("energy", "consum", "unit", "usage", "kwh", "demand", "load factor")):
        return "energy_consumption"
    raise MetricError("Unknown metric. Use one of: power_factor, energy_consumption, "
                      "load_utilisation, consumption_share, top_consumers.")


def compute_metric(metric, identifier, days, user):
    """Run one metric as `user`. Raises MetricError or access.AccessDenied."""
    kind = normalise_metric(metric)
    days = max(1, min(int(days or 7), MAX_DAYS))

    conn = access.trusted_connection()
    try:
        entity = resolve_entity(conn, identifier, user)

        if not user.is_admin:
            if entity["type"] != "LT" or entity["scno"] != user.consumer_ref:
                raise access.AccessDenied("You can only see figures for your own connection.")
            if kind == "top_consumers":
                raise access.AccessDenied("Rankings of other consumers are available to administrators only.")
            if kind == "consumption_share" and not config.USERS_CAN_SEE_DTR_SHARE:
                raise access.AccessDenied("Transformer share figures are available to administrators only.")

        if entity["type"] == "HT":
            raise MetricError(_no_interval_message(entity))
        return _HANDLERS[kind](conn, entity, days, user)
    finally:
        conn.close()
