# valg/plugins/valgresultater_fv.py
TABLE = "results"

def MATCH(filename: str) -> bool:
    return filename.startswith("valgresultater-Folketingsvalg")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []
    ao_id = str(data.get("AfstemningsområdeDagiId", ""))
    raw_type = (data.get("Resultatart") or "").lower()
    if "endelig" in raw_type or "final" in raw_type or "fintaelling" in raw_type or "fintælling" in raw_type:
        count_type = "final"
    elif "foreløbig" in raw_type or "prelim" in raw_type:
        count_type = "preliminary"
    else:
        count_type = "preliminary"

    for party in (data.get("IndenforParti") or []):
        party_id = party.get("Bogstavbetegnelse")
        party_votes = party.get("Stemmer")
        if party_votes is not None:
            rows.append({
                "afstemningsomraade_id": ao_id,
                "party_id": party_id,
                "candidate_id": None,
                "votes": party_votes,
                "count_type": count_type,
                "snapshot_at": snapshot_at,
            })
        for k in (party.get("Kandidater") or []):
            rows.append({
                "afstemningsomraade_id": ao_id,
                "party_id": party_id,
                "candidate_id": k.get("Id"),
                "votes": k.get("Stemmer"),
                "count_type": count_type,
                "snapshot_at": snapshot_at,
            })

    return [r for r in rows if r.get("afstemningsomraade_id") and r.get("votes") is not None]
