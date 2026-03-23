# valg/plugins/geografi.py
TABLE = "storkredse"

def MATCH(filename: str) -> bool:
    return filename.startswith("Region") or filename.startswith("Storkreds")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        row = {
            "id": item.get("Kode"),
            "name": item.get("Navn"),
            "n_kredsmandater": item.get("AntalKredsmandater"),
            "election_id": item.get("ValgId"),
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
