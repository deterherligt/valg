# valg/plugins/geografi_kommune.py
TABLE = "kommuner"

def MATCH(filename: str) -> bool:
    return filename.startswith("Kommune-") or filename.startswith("Kommune.")

def parse(data, snapshot_at: str) -> list:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        dagi_id = item.get("Dagi_id")
        name = item.get("Navn")
        if dagi_id and name:
            rows.append({
                "id": str(dagi_id),
                "code": item.get("Kode"),
                "name": name,
                "region_id": str(item.get("Regionskode", "")),
            })
    return rows
