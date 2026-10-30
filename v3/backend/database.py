"""
Builds and seeds the local SQLite copy of the epdatalake tables.

Table and column names follow the "LLM Data Retrieval and Table Mapping" reference.
Only tables whose columns are documented there are created, so the three billing tables
are left out (the reference says to DESCRIBE them first and we have no real schema).

Two things go beyond the reference, on purpose:
  * fdr_dtr_newcharge and t_nw_blp are created because the DTR AMR meter path needs them.
  * The reading tables (t_blp_sp, t_blp_tp, t_nw_blp) get an extra column, wh_imp (active
    energy, Wh). The reference only names msn, ts and vah_imp and says the rest is
    undocumented. Power factor = Wh / VAh, so it can't be calculated without it. If your real
    tables use another name for active energy, change it here and in metrics.py.

The data is built so the numbers agree with each other: a DTR meter reads the sum of all its
consumers plus a few percent of losses. That is what makes "share of the transformer" and
"transformer loading" come out meaningful.

Rebuild by hand with:   python database.py --reset
An older file (different SCHEMA_VERSION) is rebuilt automatically on startup.
"""

import argparse
import itertools
import math
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "epdatalake_local.db"

SCHEMA_VERSION = 2          # bump when tables change, an older file is rebuilt on startup
INTERVAL_MINUTES = 15
INTERVAL_HOURS = INTERVAL_MINUTES / 60
READING_DAYS = 7

TABLE_NAMES = [
    "dtr_master",
    "consumer_mapping",
    "lt_consumer_master",
    "ht_consumer_master",
    "smart_meters_install_m",
    "t_blp_sp",
    "t_blp_tp",
    "lt_meter_data",
    "lt_category_master",
    "fdr_dtr_newcharge",
    "t_nw_blp",
]

# Join keys J1..J8 from section 3 of the reference are real foreign keys here.
# J9 (category) is unconfirmed in the reference, so it is NOT enforced.
SCHEMA = """
CREATE TABLE dtr_master (
    ID                  INTEGER PRIMARY KEY,
    DTR_STRUCTURE_CODE  TEXT NOT NULL UNIQUE,
    DTR_LOCATION        TEXT,
    FEEDER_CODE         TEXT,
    PHASE               TEXT,
    CAPACITY            REAL,            -- kVA
    NO_OF_METERS        INTEGER,
    METER_NUM_1         TEXT,
    METER_NUM_2         TEXT,
    METER_NUM_3         TEXT,
    GLAT                REAL,
    GLONG               REAL
);

CREATE TABLE lt_consumer_master (
    ID                  INTEGER PRIMARY KEY,   -- used by lt_meter_data.CONS_NUMBER
    SCNO                TEXT NOT NULL UNIQUE,  -- used by consumer_mapping.CONS_NO
    UKSCNO              TEXT UNIQUE,           -- used by smart_meters_install_m
    NAME                TEXT,
    CATEGORY            TEXT,
    PHASE               TEXT,
    CONTRACTED_LOAD     REAL,                  -- kW
    CONNECTED_LOAD      REAL,                  -- kW
    LOAD_TYPE           TEXT,
    FEEDER_NUM          TEXT,
    TRANS_STRUC_CODE    TEXT,
    BILLING_STATUS      TEXT,
    SM_MTR              TEXT,                  -- supporting flag only
    NET_METERING        TEXT
);

CREATE TABLE consumer_mapping (
    DTR_STRUC_CODE      TEXT NOT NULL REFERENCES dtr_master (DTR_STRUCTURE_CODE),   -- J1
    CONS_NO             TEXT NOT NULL REFERENCES lt_consumer_master (SCNO),         -- J2
    PRIMARY KEY (DTR_STRUC_CODE, CONS_NO)
);

CREATE TABLE ht_consumer_master (
    ID                  INTEGER PRIMARY KEY,
    CONS_NUMBER         TEXT NOT NULL UNIQUE,
    NAME                TEXT,
    TYPE_OF_SUPPLY      TEXT,
    CATEGORY            TEXT,
    POWER_LOAD          REAL,
    CONTRACT_DEMAND     REAL,
    CONNECTED_LOAD      REAL,
    SUPPLY_VOLTAGE      REAL,
    ACTUAL_VOLTAGE      REAL,
    FEEDER_NUM          TEXT,
    FEEDER_CODE         TEXT,
    TRANS_STRUC_CODE    TEXT,
    TRANS_LOCATION      TEXT,
    TRANS_SER_NUM       TEXT,
    MTR_NO              TEXT,
    METER_MAKE          TEXT,
    METER_TYPE          TEXT,
    METERING_TYPE       TEXT,
    LATITUDE            REAL,
    LONGITUDE           REAL,
    SMT_MTR             TEXT
);

CREATE TABLE smart_meters_install_m (
    UKSCNO              TEXT NOT NULL UNIQUE REFERENCES lt_consumer_master (UKSCNO),  -- J5
    MTR_SNO             TEXT NOT NULL UNIQUE,
    MTR_TYPE            TEXT,
    CONSUMER_MOBILENO   TEXT,
    LATITUDE            REAL,
    LONGITUDE           REAL
);

CREATE TABLE t_blp_sp (
    msn                 TEXT NOT NULL REFERENCES smart_meters_install_m (MTR_SNO),    -- J6
    ts                  TEXT NOT NULL,
    vah_imp             REAL,                  -- apparent energy in the interval, VAh
    wh_imp              REAL,                  -- active energy in the interval, Wh (added, see top)
    PRIMARY KEY (msn, ts)
);

CREATE TABLE t_blp_tp (
    msn                 TEXT NOT NULL REFERENCES smart_meters_install_m (MTR_SNO),    -- J7
    ts                  TEXT NOT NULL,
    vah_imp             REAL,
    wh_imp              REAL,
    PRIMARY KEY (msn, ts)
);

CREATE TABLE lt_meter_data (
    ID                  INTEGER PRIMARY KEY AUTOINCREMENT,
    CONS_NUMBER         INTEGER NOT NULL REFERENCES lt_consumer_master (ID),          -- J8 (holds ID, not SCNO)
    PRESENT_READING     REAL,                  -- kWh register
    PREV_READING        REAL,
    PRESENT_MTRRDDATE   TEXT,
    PREV_MTRRDDATE      TEXT
);

CREATE TABLE lt_category_master (
    ID                  INTEGER PRIMARY KEY,
    NAME                TEXT,
    CAT_CODE            TEXT,
    SCDESC              TEXT
);

CREATE TABLE fdr_dtr_newcharge (
    DTR_ID                          TEXT NOT NULL REFERENCES dtr_master (DTR_STRUCTURE_CODE),  -- J3, holds the structure code
    DTR_MASTER_ID                   INTEGER REFERENCES dtr_master (ID),
    NEW_MTR_MSN                     TEXT NOT NULL UNIQUE,
    NEW_MTR_MAKE                    TEXT,
    NEW_MTR_MF                      REAL,
    NEW_MTR_CT_RATIO                TEXT,
    NEW_MTR_PT_RATIO                TEXT,
    NEW_MTR_INSTALLATION_DATETIME   TEXT
);

CREATE TABLE t_nw_blp (
    msn                 TEXT NOT NULL REFERENCES fdr_dtr_newcharge (NEW_MTR_MSN),     -- J4
    ts                  TEXT NOT NULL,
    vah_imp             REAL,
    wh_imp              REAL,
    PRIMARY KEY (msn, ts)
);
"""

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

# code, location, feeder, capacity kVA, peak loading target, lat, long, number of LT consumers
# The loading targets make the demo interesting: DTR-1006 ends up overloaded, DTR-1005 is near its limit.
DTRS = [
    ("DTR-1001", "Uppal Industrial Area", "FDR-UPL-01", 100, 0.62, 17.4018, 78.5602, 8),
    ("DTR-1002", "Nacharam Phase 2", "FDR-NCH-02", 100, 0.55, 17.4273, 78.5551, 7),
    ("DTR-1003", "Kukatpally Housing Board", "FDR-KPY-01", 63, 0.78, 17.4948, 78.3996, 6),
    ("DTR-1004", "Jeedimetla Industrial Estate", "FDR-JDM-04", 160, 0.48, 17.5086, 78.4430, 6),
    ("DTR-1005", "Patancheru Main Road", "FDR-PTR-03", 63, 0.91, 17.5334, 78.2647, 5),
    ("DTR-1006", "Medchal Town", "FDR-MDC-01", 63, 1.12, 17.6297, 78.4813, 4),
]

CATEGORIES = [
    (1, "DOMESTIC", "CAT1", "Domestic - LT Category I"),
    (2, "COMMERCIAL", "CAT2", "Commercial - LT Category II"),
    (3, "INDUSTRIAL", "CAT3", "Industrial - LT Category III"),
    (4, "AGRICULTURE", "CAT5", "Agriculture - LT Category V"),
]

FIRST_NAMES = ["Ravi", "Anitha", "Suresh", "Lakshmi", "Venkat", "Padma", "Kiran",
               "Sravani", "Mahesh", "Divya", "Naveen", "Swathi", "Ramesh", "Harika",
               "Srinivas", "Meena", "Arjun", "Bhavani", "Prasad", "Kavitha"]
LAST_NAMES = ["Reddy", "Rao", "Sharma", "Naidu", "Goud", "Varma", "Chary", "Kumar",
              "Yadav", "Patel", "Raju", "Babu"]

# Power factor ranges by category (industrial loads with motors run lower)
PF_RANGE = {"DOMESTIC": (0.93, 0.98), "COMMERCIAL": (0.89, 0.95), "INDUSTRIAL": (0.82, 0.90)}

# Hand-picked consumers so there is something to find in the data
POOR_PF_CONSUMER = 5       # industrial, smart, power factor around 0.76
OVER_CONTRACT_CONSUMER = 9 # smart, peak demand above its contracted load

# The three plants are HT consumers. The reference does not document any link from HT
# consumers to DTRs (section 7), and no HT readings table, so they only have master data.
HT_PLANTS = [
    # name, supply, contract demand kVA, connected load kW, lat, long
    ("Plant A", "11 kV", 1500, 1380, 17.5121, 78.4502),
    ("Plant B", "33 kV", 4500, 4100, 17.5402, 78.2790),
    ("Plant C", "11 kV", 800, 720, 17.4066, 78.5718),
]


def _load_shape(hour_float):
    """Rough daily load curve: low overnight, a morning bump, bigger evening peak."""
    morning = math.exp(-((hour_float - 9) ** 2) / 8)
    evening = 1.3 * math.exp(-((hour_float - 19.5) ** 2) / 6)
    return 0.45 + 0.35 * morning + 0.5 * evening


_SHAPE_MAX = max(_load_shape(i / 4) for i in range(96))


def _timestamps():
    end = datetime.now().replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % INTERVAL_MINUTES)
    steps = READING_DAYS * 24 * 60 // INTERVAL_MINUTES
    return [end - timedelta(minutes=INTERVAL_MINUTES * i) for i in range(steps - 1, -1, -1)]


def _interval_series(rng, stamps, peak_kva, pf_base):
    """One (VAh, Wh) pair per interval for a load whose busiest moment is about peak_kva."""
    series = []
    for ts in stamps:
        shape = _load_shape(ts.hour + ts.minute / 60) / _SHAPE_MAX      # 0..1
        kva = peak_kva * shape * rng.uniform(0.93, 1.03)
        pf = pf_base - 0.05 * (1 - shape) + rng.uniform(-0.012, 0.012)   # worse when lightly loaded
        pf = min(0.995, max(0.60, pf))
        vah = kva * 1000 * INTERVAL_HOURS
        series.append((vah, vah * pf))
    return series


def _monthly_dates(count):
    today = date.today()
    return [today - timedelta(days=30 * i) for i in range(count, -1, -1)]


def _round_half(value):
    return max(1.0, round(value * 2) / 2)


def _plan_consumers(rng, count, first_number):
    """Decide phase, category, weight and power factor for the consumers of one DTR."""
    plans = []
    for k in range(count):
        number = first_number + k
        phase = rng.choices(["1 Phase", "3 Phase"], weights=[65, 35])[0]
        if number == POOR_PF_CONSUMER:
            phase = "3 Phase"
        plans.append({"number": number, "phase": phase})

    if not any(p["phase"] == "3 Phase" for p in plans):
        plans[-1]["phase"] = "3 Phase"      # every transformer has at least one big customer

    for p in plans:
        if p["phase"] == "1 Phase":
            p["category"] = rng.choices(["DOMESTIC", "COMMERCIAL"], weights=[85, 15])[0]
            p["weight"] = rng.uniform(0.8, 1.4)
        else:
            p["category"] = rng.choice(["COMMERCIAL", "INDUSTRIAL"])
            p["weight"] = rng.uniform(4.0, 7.0)
        p["util"] = rng.uniform(0.40, 0.80)
        p["pf"] = rng.uniform(*PF_RANGE[p["category"]])
        p["smart"] = rng.random() < 0.65

        if p["number"] == POOR_PF_CONSUMER:
            p.update(category="INDUSTRIAL", pf=0.76, smart=True)
        if p["number"] == OVER_CONTRACT_CONSUMER:
            p.update(util=1.18, smart=True)
    return plans


def seed(conn, rng):
    cur = conn.cursor()
    stamps = _timestamps()
    stamp_text = [t.strftime("%Y-%m-%d %H:%M:%S") for t in stamps]

    cur.executemany("INSERT INTO lt_category_master VALUES (?,?,?,?)", CATEGORIES)

    names = list(itertools.product(FIRST_NAMES, LAST_NAMES))
    rng.shuffle(names)
    names = [f"{first} {last}" for first, last in names]     # all different

    consumer_no = 0
    sm_flag_trap_used = False

    for dtr_idx, (code, location, feeder, cap_kva, target, lat, lon, count) in enumerate(DTRS, start=1):
        plans = _plan_consumers(rng, count, consumer_no + 1)
        loss = rng.uniform(0.04, 0.07)

        # the DTR row must exist before consumers are mapped to it (foreign key)
        msn = f"DTRM{2000 + dtr_idx}"
        cur.execute(
            "INSERT INTO dtr_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (dtr_idx, code, location, feeder, "3 Phase", cap_kva, 1, msn, None, None, lat, lon),
        )

        # size every customer so the transformer peaks near its loading target
        dtr_peak_kva = cap_kva * target
        total_weight = sum(p["weight"] for p in plans)
        dtr_vah = [0.0] * len(stamps)
        dtr_wh = [0.0] * len(stamps)
        mapped = []

        for p in plans:
            consumer_no += 1
            peak_kva = dtr_peak_kva / (1 + loss) * p["weight"] / total_weight
            contracted = _round_half(peak_kva * p["pf"] / p["util"])
            if p["phase"] == "1 Phase" and contracted > 10:
                p["phase"] = "3 Phase"      # no real single-phase connection is that big
            series = _interval_series(rng, stamps, peak_kva, p["pf"])

            for i, (vah, wh) in enumerate(series):
                dtr_vah[i] += vah
                dtr_wh[i] += wh

            cons_id = 5000 + consumer_no
            scno = f"72{consumer_no:05d}"
            ukscno = f"UK{9000000 + consumer_no}"
            sm_flag = "Y" if p["smart"] else "N"
            # One non-smart consumer is flagged Y without an install row. The reference warns that
            # SM_MTR alone can't be trusted, so we keep a case that proves it.
            if not p["smart"] and not sm_flag_trap_used:
                sm_flag = "Y"
                sm_flag_trap_used = True

            cur.execute(
                "INSERT INTO lt_consumer_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cons_id, scno, ukscno, names[consumer_no - 1], p["category"], p["phase"],
                 contracted, round(contracted * 1.1, 1), "KW", feeder, code,
                 rng.choices(["ACTIVE", "DISCONNECTED"], weights=[94, 6])[0],
                 sm_flag, "Y" if rng.random() < 0.05 else "N"),
            )
            cur.execute("INSERT INTO consumer_mapping VALUES (?,?)", (code, scno))

            if p["smart"]:
                mtr_sno = f"SM{4100000 + consumer_no}"
                cur.execute(
                    "INSERT INTO smart_meters_install_m VALUES (?,?,?,?,?,?)",
                    (ukscno, mtr_sno, "1PH SMART" if p["phase"] == "1 Phase" else "3PH SMART",
                     "9" + "".join(rng.choice("0123456789") for _ in range(9)),
                     round(lat + rng.uniform(-0.02, 0.02), 5), round(lon + rng.uniform(-0.02, 0.02), 5)),
                )
                table = "t_blp_sp" if p["phase"] == "1 Phase" else "t_blp_tp"
                cur.executemany(
                    f"INSERT INTO {table} VALUES (?,?,?,?)",
                    [(mtr_sno, stamp_text[i], round(v, 2), round(w, 2)) for i, (v, w) in enumerate(series)],
                )
            else:
                # non-smart: monthly manual reads in lt_meter_data (kWh register), keyed by ID
                avg_kw = sum(w for _, w in series) / 1000 / (len(series) * INTERVAL_HOURS)
                dates = _monthly_dates(6)
                reading = rng.randint(1000, 8000)
                for prev_date, present_date in zip(dates, dates[1:]):
                    units = round(avg_kw * 24 * 30 * rng.uniform(0.9, 1.1))
                    cur.execute(
                        "INSERT INTO lt_meter_data "
                        "(CONS_NUMBER, PRESENT_READING, PREV_READING, PRESENT_MTRRDDATE, PREV_MTRRDDATE) "
                        "VALUES (?,?,?,?,?)",
                        (cons_id, reading + units, reading, present_date.isoformat(), prev_date.isoformat()),
                    )
                    reading += units
            mapped.append(scno)

        # The DTR's own AMR meter: everything its consumers draw, plus losses
        cur.execute(
            "INSERT INTO fdr_dtr_newcharge VALUES (?,?,?,?,?,?,?,?)",
            (code, dtr_idx, msn, rng.choice(["Secure", "Genus", "L&T", "HPL"]), 1,
             f"{int(cap_kva * 2)}/5", "415/110",
             (datetime.now() - timedelta(days=rng.randint(200, 900))).strftime("%Y-%m-%d %H:%M:%S")),
        )
        cur.executemany(
            "INSERT INTO t_nw_blp VALUES (?,?,?,?)",
            [(msn, stamp_text[i], round(dtr_vah[i] * (1 + loss) * rng.uniform(0.997, 1.003), 2),
              round(dtr_wh[i] * (1 + loss), 2)) for i in range(len(stamps))],
        )

    # --- HT consumers (Plant A/B/C) -------------------------------------------
    for idx, (name, supply, demand, connected, lat, lon) in enumerate(HT_PLANTS, start=1):
        voltage = 11000 if supply == "11 kV" else 33000
        cur.execute(
            "INSERT INTO ht_consumer_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (idx, f"HT{1000 + idx}", name, supply, "HT-I INDUSTRIAL",
             connected, demand, connected + 60, voltage,
             voltage + rng.randint(-250, 250), f"FDR-HT-{idx:02d}", f"HTF{idx}",
             f"HTR-{3000 + idx}", f"{name} Substation", f"TR{880000 + idx}",
             f"HTM{7000 + idx}", rng.choice(["Secure", "L&T", "Genus"]), "HT TOD",
             "HT-CT-PT", lat, lon, "Y"),
        )

    conn.commit()


def _file_version():
    """user_version stored in the file, None if there is no file, -1 if it can't be read."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return -1


def init_db(reset=False):
    """
    Create the database if it is missing or built from an older schema.
    Returns True when it was (re)built.
    """
    if _file_version() == SCHEMA_VERSION and not reset:
        return False
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        seed(conn, random.Random(42))  # fixed seed so everyone sees the same rows
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"Seed data breaks {len(broken)} join key(s): {broken[:3]}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the local epdatalake SQLite file")
    parser.add_argument("--reset", action="store_true", help="delete and rebuild the database")
    args = parser.parse_args()

    built = init_db(reset=args.reset)
    print(f"{'Built' if built else 'Already up to date, left untouched'}: {DB_PATH}")
    check = sqlite3.connect(DB_PATH)
    for name in TABLE_NAMES:
        count = check.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name:<24}{count:>7} rows")
    check.close()
