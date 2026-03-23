from __future__ import annotations
# valg/plugins/valgdeltagelse.py
TABLE = "turnout"

def MATCH(filename: str) -> bool:
    return filename.startswith("valgdeltagelse")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []
    ao_id = str(data.get("AfstemningsområdeDagiId", ""))
    for entry in (data.get("Valgdeltagelse") or []):
        rows.append({
            "afstemningsomraade_id": ao_id,
            "eligible_voters": entry.get("AntalStemmeberretigedeVælgere") or entry.get("AntalStemmeberettigede"),
            "votes_cast": entry.get("AfgivneStemmer"),
            "snapshot_at": snapshot_at,
        })
    return [r for r in rows if r.get("afstemningsomraade_id")]
