# valg/plugins/geografi_ao.py
TABLE = "afstemningsomraader"

def MATCH(filename: str) -> bool:
    return filename.startswith("Afstemningsomraade-")

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
            "opstillingskreds_id": str(item.get("Opstillingskreds_Dagi_id", "")),
            "municipality_name": None,
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
