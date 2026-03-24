from __future__ import annotations
# valg/processor.py
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from valg.plugins import find_plugin

log = logging.getLogger(__name__)

_LETTER_MAP = {"Æ": "Ae", "Ø": "Oe", "Å": "Aa"}


def _extract_parties(conn, data: dict) -> None:
    """Extract party names from partistemmefordeling or kandidat-data into parties table."""
    for party in (data.get("IndenforParti") or []):
        letter = party.get("Bogstavbetegnelse") or party.get("Partibogstav") or ""
        name = party.get("PartiNavn") or party.get("Partinavn") or ""
        if not letter:
            continue
        normalized = _LETTER_MAP.get(letter, letter)
        if name and name != letter:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO parties (id, letter, name, election_id) VALUES (?, ?, ?, ?)",
                    (normalized, normalized, name, "fv2026"),
                )
            except Exception:
                pass
        else:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO parties (id, letter, name, election_id) VALUES (?, ?, ?, ?)",
                    (normalized, normalized, normalized, "fv2026"),
                )
            except Exception:
                pass
    valg = data.get("Valg")
    if valg and isinstance(valg, dict):
        for party in (valg.get("Partier") or []):
            party_id = party.get("PartiId") or ""
            if not party_id:
                continue
            normalized = _LETTER_MAP.get(party_id, party_id)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO parties (id, letter, name, election_id) VALUES (?, ?, ?, ?)",
                    (normalized, normalized, normalized, "fv2022"),
                )
            except Exception:
                pass
    conn.commit()


# Map plugin TABLE names to the columns that constitute a unique row.
# Geography/reference tables use INSERT OR REPLACE (natural key upsert).
# Snapshot tables use INSERT OR IGNORE (immutable snapshots).
_UPSERT_KEYS: dict[str, list[str]] = {
    "valglandsdele":       ["id"],
    "regioner":            ["id"],
    "kommuner":            ["id"],
    "storkredse":          ["id"],
    "opstillingskredse":   ["id"],
    "afstemningsomraader": ["id"],
    "parties":             ["id"],
    "candidates":          ["id"],
    "results":             ["afstemningsomraade_id", "party_id", "candidate_id", "count_type", "snapshot_at"],
    "turnout":             ["afstemningsomraade_id", "snapshot_at"],
    "party_votes":         ["opstillingskreds_id", "party_id", "snapshot_at"],
}

# Reference tables that use INSERT OR REPLACE (idempotent upsert by natural key).
_REPLACE_TABLES = {"valglandsdele", "regioner", "kommuner", "storkredse", "opstillingskredse", "afstemningsomraader", "parties", "candidates"}


def _emit_event(conn, occurred_at: str, event_type: str, subject: str, description: str) -> None:
    try:
        conn.execute(
            "INSERT INTO events (occurred_at, event_type, subject, description) VALUES (?,?,?,?)",
            (occurred_at, event_type, subject, description),
        )
        conn.commit()
    except Exception as e:
        log.warning("Failed to emit event: %s", e)


def _log_anomaly(conn, filename: str, anomaly_type: str, detail: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO anomalies (detected_at, filename, anomaly_type, detail) VALUES (?,?,?,?)",
            (now, filename, anomaly_type, detail),
        )
        conn.commit()
    except Exception as e:
        log.error("Failed to log anomaly: %s", e)


def _get_schema_columns(conn, table: str) -> set[str]:
    """Return the set of column names for a table."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _insert_rows(conn, table: str, rows: list[dict]) -> int:
    """
    Insert rows into table, using upsert for known tables. Returns inserted count.
    FK enforcement is disabled during bulk insert to allow ETL without pre-existing
    reference data; integrity is validated separately.
    """
    if not rows:
        return 0

    schema_cols = _get_schema_columns(conn, table)
    inserted = 0

    # Disable FK enforcement for ETL inserts — processor trusts source data.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        for row in rows:
            # Filter to only known columns; log and skip unknown fields.
            unknown = [k for k in row if k not in schema_cols]
            if unknown:
                log.debug("Unknown fields for table %s, skipping: %s", table, unknown)
            filtered = {k: v for k, v in row.items() if k in schema_cols}
            if not filtered:
                continue

            cols = list(filtered.keys())
            placeholders = ", ".join("?" for _ in cols)
            col_str = ", ".join(cols)

            upsert_keys = _UPSERT_KEYS.get(table, [])
            if table in _REPLACE_TABLES and upsert_keys and all(k in cols for k in upsert_keys):
                sql = f"INSERT OR REPLACE INTO {table} ({col_str}) VALUES ({placeholders})"
            else:
                sql = f"INSERT OR IGNORE INTO {table} ({col_str}) VALUES ({placeholders})"

            try:
                conn.execute(sql, list(filtered.values()))
                inserted += 1
            except Exception as e:
                log.warning("Insert failed for %s: %s | row=%s", table, e, filtered)

        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys=ON")

    return inserted


def process_raw_file(
    conn,
    file_path: Path,
    snapshot_at: str | None = None,
) -> int:
    """
    Process a single raw JSON file: find plugin, parse, insert rows.
    Returns number of rows inserted. Never raises.
    """
    filename = file_path.name
    if snapshot_at is None:
        snapshot_at = datetime.now(timezone.utc).isoformat()

    # Skip empty files (truncated downloads)
    raw = file_path.read_text(encoding="utf-8").strip()
    if not raw:
        log.debug("Empty file, skipping: %s", filename)
        return 0

    # Parse JSON
    try:
        data = json.loads(raw)
    except Exception as e:
        log.warning("JSON parse failure: %s — %s", filename, e)
        _log_anomaly(conn, filename, "parse_failure", str(e))
        return 0

    # Find plugin
    plugin = find_plugin(filename)
    if plugin is None:
        log.info("No plugin for %s — skipping", filename)
        _log_anomaly(conn, filename, "unknown_file", f"No plugin registered for {filename}")
        return 0

    # Parse and insert
    try:
        rows = plugin.parse(data, snapshot_at)
    except Exception as e:
        log.warning("Plugin parse error for %s: %s", filename, e)
        _log_anomaly(conn, filename, "parse_failure", str(e))
        return 0

    inserted = _insert_rows(conn, plugin.TABLE, rows)

    # Extract parties from partistemmefordeling or kandidat-data
    if plugin.TABLE in ("party_votes", "candidates") and isinstance(data, dict):
        _extract_parties(conn, data)

    if plugin.TABLE == "results" and inserted > 0:
        ao_id = rows[0].get("afstemningsomraade_id", "unknown")
        count_type = rows[0].get("count_type", "unknown")
        _emit_event(conn, snapshot_at, "district_reported", ao_id, f"{count_type} results")
    elif plugin.TABLE == "turnout" and inserted > 0:
        ao_id = rows[0].get("afstemningsomraade_id", "unknown")
        _emit_event(conn, snapshot_at, "district_reported", ao_id, "preliminary results")

    return inserted


def process_directory(
    conn,
    directory: Path,
    snapshot_at: str | None = None,
) -> int:
    """
    Process all .json files in a directory (recursive).
    Returns total rows inserted.
    """
    if snapshot_at is None:
        snapshot_at = datetime.now(timezone.utc).isoformat()

    total = 0
    for f in sorted(f for f in directory.rglob("*.json") if not f.name.endswith(".schema.json")):
        total += process_raw_file(conn, f, snapshot_at=snapshot_at)
    log.info("Processed directory %s: %d rows inserted", directory, total)
    return total
