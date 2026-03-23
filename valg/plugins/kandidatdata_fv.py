# valg/plugins/kandidatdata_fv.py
TABLE = "candidates"

def MATCH(filename: str) -> bool:
    return filename.startswith("kandidat-data-Folketingsvalg") or filename.startswith("kandidat-data-fv")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []
    for party in data.get("IndenforParti", []):
        party_id = party.get("Partibogstav")
        for k in party.get("Kandidater", []):
            cand_id = k.get("Id")
            cand_name = k.get("Navn")
            if not cand_id or not cand_name:
                continue
            for ok in k.get("Opstillingskredse", []):
                if not ok.get("OpstilletIKreds"):
                    continue
                rows.append({
                    "id": cand_id,
                    "name": cand_name,
                    "party_id": party_id,
                    "opstillingskreds_id": ok.get("OpstillingskredsDagiId"),
                    "ballot_position": ok.get("KandidatsPlacering"),
                })
    return rows
