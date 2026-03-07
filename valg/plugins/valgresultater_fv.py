# valg/plugins/valgresultater_fv.py
TABLE = "results"

def MATCH(filename: str) -> bool:
    return filename.startswith("valgresultater-Folketingsvalg")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    vr = data.get("Valgresultater", {}) if isinstance(data, dict) else {}
    ao_id = vr.get("AfstemningsomraadeId")
    raw_type = vr.get("Optaellingstype", "")
    count_type = "final" if "Fintaelling" in raw_type or "intaelling" in raw_type else "preliminary"

    for party in vr.get("IndenforParti", []):
        party_id = party.get("PartiId")
        # Party-level row (no candidate)
        party_votes = party.get("Partistemmer")
        if party_votes is not None:
            rows.append({
                "afstemningsomraade_id": ao_id,
                "party_id": party_id,
                "candidate_id": None,
                "votes": party_votes,
                "count_type": count_type,
                "snapshot_at": snapshot_at,
            })
        # Candidate-level rows
        for k in party.get("Kandidater", []):
            rows.append({
                "afstemningsomraade_id": ao_id,
                "party_id": party_id,
                "candidate_id": k.get("KandidatId"),
                "votes": k.get("Stemmer"),
                "count_type": count_type,
                "snapshot_at": snapshot_at,
            })

    for k in vr.get("KandidaterUdenforParti", []):
        rows.append({
            "afstemningsomraade_id": ao_id,
            "party_id": None,
            "candidate_id": k.get("KandidatId"),
            "votes": k.get("Stemmer"),
            "count_type": count_type,
            "snapshot_at": snapshot_at,
        })

    return [r for r in rows if r.get("afstemningsomraade_id") and r.get("votes") is not None]
