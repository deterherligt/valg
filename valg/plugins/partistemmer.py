from __future__ import annotations
# valg/plugins/partistemmer.py
TABLE = "party_votes"

_LETTER_MAP = {"Æ": "Ae", "Ø": "Oe", "Å": "Aa"}

def MATCH(filename: str) -> bool:
    return filename.startswith("partistemmefordeling")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    rows = []
    if not isinstance(data, dict):
        return []

    # 2026 format: flat dict with OpstillingskredsDagiId + IndenforParti
    # FV2022 format: {"Valg": {"OpstillingskredsId": ..., "Partier": [...]}}
    valg = data.get("Valg")
    if valg and isinstance(valg, dict):
        ok_id = str(valg.get("OpstillingskredsId", ""))
        for party in (valg.get("Partier") or []):
            letter = party.get("PartiId") or ""
            rows.append({
                "opstillingskreds_id": ok_id,
                "party_id": _LETTER_MAP.get(letter, letter),
                "votes": party.get("Stemmer"),
                "snapshot_at": snapshot_at,
            })
    else:
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
