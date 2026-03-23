# valg/plugins/geografi_region.py
TABLE = "regioner"

def MATCH(filename: str) -> bool:
    return filename.startswith("Region-") or filename.startswith("Region.")

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
            })
    return rows
