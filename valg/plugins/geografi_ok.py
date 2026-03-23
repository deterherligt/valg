from __future__ import annotations
# valg/plugins/geografi_ok.py
TABLE = "opstillingskredse"

def MATCH(filename: str) -> bool:
    return filename.startswith("Opstillingskreds-")

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
            "storkreds_id": str(item.get("Storkredskode") or item.get("StorkredskodeKode") or ""),
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
