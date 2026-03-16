# valg/plugins/geografi_ok.py
TABLE = "opstillingskredse"

def MATCH(filename: str) -> bool:
    return filename.startswith("Opstillingskreds-")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        row = {
            "id": item.get("Kode"),
            "name": item.get("Navn"),
            "storkreds_id": item.get("StorkredskodeKode"),
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
