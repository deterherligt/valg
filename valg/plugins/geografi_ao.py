# valg/plugins/geografi_ao.py
TABLE = "afstemningsomraader"

def MATCH(filename: str) -> bool:
    return filename.startswith("Afstemningsomraade-")

def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        row = {
            "id": item.get("Kode"),
            "name": item.get("Navn"),
            "opstillingskreds_id": item.get("OpstillingskredsKode"),
            "eligible_voters": item.get("AntalStemmeberettigede"),
        }
        if row["id"] and row["name"]:
            rows.append(row)
    return rows
