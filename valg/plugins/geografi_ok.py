# valg/plugins/geografi_ok.py
TABLE = "opstillingskredse"

def MATCH(filename: str) -> bool:
    return filename.startswith("Opstillingskreds-")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        dagi_id = item.get("Dagi_id")
        if not dagi_id:
            continue
        row = {
            "id": str(dagi_id),
            "name": item.get("Navn"),
            "storkreds_id": str(item.get("Storkredskode", "")),
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
