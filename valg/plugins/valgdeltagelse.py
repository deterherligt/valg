# valg/plugins/valgdeltagelse.py
TABLE = "turnout"

def MATCH(filename: str) -> bool:
    return filename.startswith("valgdeltagelse")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    valg = data.get("Valg", {}) if isinstance(data, dict) else {}
    ao_id = valg.get("AfstemningsomraadeId")
    for entry in valg.get("Valgdeltagelse", []):
        rows.append({
            "afstemningsomraade_id": ao_id,
            "eligible_voters": entry.get("StemmeberettigedeVaelgere"),
            "votes_cast": entry.get("AfgivneStemmer"),
            "snapshot_at": snapshot_at,
        })
    return [r for r in rows if r.get("afstemningsomraade_id")]
