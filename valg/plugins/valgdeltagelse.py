from __future__ import annotations
# valg/plugins/valgdeltagelse.py
TABLE = "turnout"

def MATCH(filename: str) -> bool:
    return filename.startswith("valgdeltagelse")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []
    # Try both Unicode (2026) and ASCII (fv2022) field names
    ao_id = str(data.get("AfstemningsområdeDagiId") or data.get("AfstemningsomraadeDagiId") or "")
    for entry in (data.get("Valgdeltagelse") or []):
        rows.append({
            "afstemningsomraade_id": ao_id,
            "eligible_voters": (entry.get("AntalStemmeberretigedeVælgere")
                                or entry.get("AntalStemmeberettigede")
                                or entry.get("AntalStemmeberretigedeVaelgere")),
            "votes_cast": entry.get("AfgivneStemmer"),
            "snapshot_at": snapshot_at,
        })
    return [r for r in rows if r.get("afstemningsomraade_id")]
