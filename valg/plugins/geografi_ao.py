from __future__ import annotations
# valg/plugins/geografi_ao.py
TABLE = "afstemningsomraader"

def MATCH(filename: str) -> bool:
    return filename.startswith("Afstemningsomraade-")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        item_id = item.get("Dagi_id") or item.get("Kode")
        if not item_id:
            continue
        row = {
            "id": str(item_id),
            "name": item.get("Navn"),
            "opstillingskreds_id": str(item.get("Opstillingskreds_Dagi_id") or item.get("OpstillingskredsKode") or ""),
            "municipality_name": None,
            "eligible_voters": item.get("AntalStemmeberettigede"),
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
