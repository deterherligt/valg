# valg/plugins/partistemmer.py
TABLE = "party_votes"

def MATCH(filename: str) -> bool:
    return filename.startswith("partistemmefordeling")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    valg = data.get("Valg", {}) if isinstance(data, dict) else {}
    ok_id = valg.get("OpstillingskredsId")
    for party in valg.get("Partier", []):
        rows.append({
            "opstillingskreds_id": ok_id,
            "party_id": party.get("PartiId"),
            "votes": party.get("Stemmer"),
            "snapshot_at": snapshot_at,
        })
    return [r for r in rows if r.get("opstillingskreds_id") and r.get("party_id")]
