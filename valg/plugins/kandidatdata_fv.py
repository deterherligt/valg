# valg/plugins/kandidatdata_fv.py
TABLE = "candidates"

def MATCH(filename: str) -> bool:
    return filename.startswith("kandidat-data-Folketingsvalg")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    valg = data.get("Valg", {}) if isinstance(data, dict) else {}
    election_id = valg.get("Id")
    for party in valg.get("IndenforParti", []):
        party_id = party.get("Id")
        for k in party.get("Kandidater", []):
            rows.append({
                "id": k.get("Id"),
                "name": k.get("Navn"),
                "party_id": party_id,
                "ballot_position": k.get("Stemmeseddelplacering"),
                "election_id": election_id,
            })
    for k in valg.get("UdenforParti", {}).get("Kandidater", []):
        rows.append({
            "id": k.get("Id"),
            "name": k.get("Navn"),
            "party_id": None,
            "ballot_position": None,
            "election_id": election_id,
        })
    return [r for r in rows if r.get("id") and r.get("name")]
