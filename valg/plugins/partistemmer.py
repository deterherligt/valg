# valg/plugins/partistemmer.py
TABLE = "party_votes"

def MATCH(filename: str) -> bool:
    return filename.startswith("partistemmefordeling")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []
    ok_id = str(data.get("OpstillingskredsDagiId", ""))
    for party in (data.get("IndenforParti") or []):
        rows.append({
            "opstillingskreds_id": ok_id,
            "party_id": party.get("Bogstavbetegnelse"),
            "votes": party.get("Stemmer"),
            "snapshot_at": snapshot_at,
        })
    return [r for r in rows if r.get("opstillingskreds_id") and r.get("party_id")]
