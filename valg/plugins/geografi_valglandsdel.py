# valg/plugins/geografi_valglandsdel.py
TABLE = "valglandsdele"

def MATCH(filename: str) -> bool:
    return filename.startswith("Valglandsdel-") or filename.startswith("Valglandsdel.")

def parse(data, snapshot_at: str) -> list:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        bogstav = item.get("Bogstav")
        name = item.get("Navn")
        if bogstav and name:
            rows.append({"id": bogstav, "name": name})
    return rows
