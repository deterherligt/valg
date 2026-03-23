from __future__ import annotations
# valg/plugins/geografi.py
TABLE = "storkredse"

# Kredsmandater per storkreds — fixed by law (Folketingsvalglov bilag 3)
_KREDSMANDATER = {
    "1": 18, "København": 18,
    "2": 12, "Københavns Omegn": 12,
    "3": 9,  "Nordsjælland": 9,
    "4": 2,  "Bornholm": 2,
    "5": 18, "Sjælland": 18,
    "6": 12, "Fyn": 12,
    "7": 19, "Sydjylland": 19,
    "8": 16, "Østjylland": 16,
    "9": 16, "Vestjylland": 16,
    "10": 13, "Nordjylland": 13,
}

def MATCH(filename: str) -> bool:
    return filename.startswith("Storkreds")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        sk_id = str(item.get("Nummer") or item.get("Kode") or "")
        name = item.get("Navn")
        row = {
            "id": sk_id,
            "name": name,
            "n_kredsmandater": item.get("AntalKredsmandater") or _KREDSMANDATER.get(sk_id) or _KREDSMANDATER.get(name),
            "election_id": item.get("ValgId") or "fv2026",
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
