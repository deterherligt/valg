# valg/plugins/geografi.py
TABLE = "storkredse"

def MATCH(filename: str) -> bool:
    return filename.startswith("Storkreds")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        row = {
            "id": str(item.get("Nummer")),
            "name": item.get("Navn"),
            "election_id": "fv2026",
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
