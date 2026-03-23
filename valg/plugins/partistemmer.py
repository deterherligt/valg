# valg/plugins/partistemmer.py
TABLE = "party_votes"

# valg.dk uses Danish letters (Æ, Ø, Å) but kandidat-data uses digraphs (Ae, Oe, Aa)
_LETTER_MAP = {"Æ": "Ae", "Ø": "Oe", "Å": "Aa"}

def MATCH(filename: str) -> bool:
    return filename.startswith("partistemmefordeling")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []
    ok_id = str(data.get("OpstillingskredsDagiId", ""))
    for party in (data.get("IndenforParti") or []):
        letter = party.get("Bogstavbetegnelse") or ""
        rows.append({
            "opstillingskreds_id": ok_id,
            "party_id": _LETTER_MAP.get(letter, letter),
            "votes": party.get("Stemmer"),
            "snapshot_at": snapshot_at,
        })
    return [r for r in rows if r.get("opstillingskreds_id") and r.get("party_id")]
