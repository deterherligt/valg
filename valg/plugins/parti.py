# valg/plugins/parti.py
TABLE = "parties"


def MATCH(filename: str) -> bool:
    return filename.startswith("Parti-")


def parse(data: dict | list, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    return [
        {"id": item.get("Id"), "letter": item.get("Bogstav"), "name": item.get("Navn")}
        for item in data
        if item.get("Id") and item.get("Navn")
    ]
