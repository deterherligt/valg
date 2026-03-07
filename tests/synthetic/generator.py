# tests/synthetic/generator.py
"""
Synthetic election generator for testing.

Generates a complete in-memory election with:
- Geography: storkredse → opstillingskredse → afstemningsomraader
- Parties with letter codes
- Candidates per party per opstillingskreds
- Preliminary party vote results per district
- Final candidate vote results per district

All output is deterministic given the same seed.
"""
import random
from datetime import datetime, timezone
from typing import Optional


PARTY_LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
SNAPSHOT_NIGHT = "2024-11-05T21:00:00"
SNAPSHOT_FINAL = "2024-11-06T10:00:00"


def generate_election(
    n_parties: int = 8,
    n_storkredse: int = 5,
    n_districts: int = 50,
    seed: int = 42,
) -> dict:
    """
    Generate a complete synthetic election.

    Returns a dict with:
      election, storkredse, opstillingskredse, afstemningsomraader,
      parties, candidates
    """
    rng = random.Random(seed)

    election_id = "FV2024"
    election = {"id": election_id, "name": "Syntetisk Valg 2024", "election_date": "2024-11-05"}

    # Geography: distribute districts across storkredse and opstillingskredse
    storkredse = []
    opstillingskredse = []
    afstemningsomraader = []

    districts_per_storkreds = max(1, n_districts // n_storkredse)
    kredsmandater_pool = _distribute(135, n_storkredse, rng)

    ao_idx = 0
    for sk_i in range(n_storkredse):
        sk_id = f"SK{sk_i+1}"
        sk = {
            "id": sk_id,
            "name": f"Storkreds {sk_i+1}",
            "election_id": election_id,
            "n_kredsmandater": kredsmandater_pool[sk_i],
        }
        storkredse.append(sk)

        ok = {
            "id": f"OK{sk_i+1}",
            "name": f"Opstillingskreds {sk_i+1}",
            "storkreds_id": sk_id,
        }
        opstillingskredse.append(ok)

        for d_i in range(districts_per_storkreds):
            if ao_idx >= n_districts:
                break
            ao_id = f"AO{ao_idx+1}"
            afstemningsomraader.append({
                "id": ao_id,
                "name": f"Afstemningsområde {ao_idx+1}",
                "opstillingskreds_id": ok["id"],
                "municipality_name": f"Kommune {sk_i+1}",
                "eligible_voters": rng.randint(1000, 5000),
            })
            ao_idx += 1

    # Parties
    parties = []
    for i in range(n_parties):
        letter = PARTY_LETTERS[i]
        parties.append({
            "id": letter,
            "letter": letter,
            "name": f"Parti {letter}",
            "election_id": election_id,
        })

    # Candidates: one per party per opstillingskreds
    candidates = []
    c_idx = 0
    for ok in opstillingskredse:
        for party in parties:
            c_idx += 1
            candidates.append({
                "id": f"K{c_idx}",
                "name": f"Kandidat {c_idx}",
                "party_id": party["id"],
                "opstillingskreds_id": ok["id"],
                "ballot_position": 1,
            })

    return {
        "election": election,
        "storkredse": storkredse,
        "opstillingskredse": opstillingskredse,
        "afstemningsomraader": afstemningsomraader,
        "parties": parties,
        "candidates": candidates,
        "_rng_seed": seed,
    }


def load_into_db(conn, election: dict, phase: str = "preliminary") -> None:
    """
    Load a synthetic election into a SQLite connection.

    phase: "preliminary" — loads geography + party votes per district
           "final"       — loads candidate votes per district (does NOT reload geography)
    """
    rng = random.Random(election["_rng_seed"] + (0 if phase == "preliminary" else 1))

    if phase == "preliminary":
        _load_geography(conn, election)
        _load_parties(conn, election)
        _load_candidates(conn, election)
        _load_preliminary_results(conn, election, rng)
    elif phase == "final":
        _load_final_results(conn, election, rng)
    else:
        raise ValueError(f"Unknown phase: {phase}")


def _load_geography(conn, election: dict) -> None:
    for sk in election["storkredse"]:
        conn.execute(
            "INSERT OR REPLACE INTO elections (id, name, election_date) VALUES (?,?,?)",
            (election["election"]["id"], election["election"]["name"], election["election"]["election_date"]),
        )
        conn.execute(
            "INSERT OR REPLACE INTO storkredse (id, name, election_id, n_kredsmandater) VALUES (?,?,?,?)",
            (sk["id"], sk["name"], sk["election_id"], sk["n_kredsmandater"]),
        )
    for ok in election["opstillingskredse"]:
        conn.execute(
            "INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES (?,?,?)",
            (ok["id"], ok["name"], ok["storkreds_id"]),
        )
    for ao in election["afstemningsomraader"]:
        conn.execute(
            "INSERT OR REPLACE INTO afstemningsomraader (id, name, opstillingskreds_id, municipality_name, eligible_voters) VALUES (?,?,?,?,?)",
            (ao["id"], ao["name"], ao["opstillingskreds_id"], ao["municipality_name"], ao["eligible_voters"]),
        )
    conn.commit()


def _load_parties(conn, election: dict) -> None:
    for p in election["parties"]:
        conn.execute(
            "INSERT OR REPLACE INTO parties (id, letter, name, election_id) VALUES (?,?,?,?)",
            (p["id"], p["letter"], p["name"], p["election_id"]),
        )
    conn.commit()


def _load_candidates(conn, election: dict) -> None:
    for c in election["candidates"]:
        conn.execute(
            "INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES (?,?,?,?,?)",
            (c["id"], c["name"], c["party_id"], c["opstillingskreds_id"], c["ballot_position"]),
        )
    conn.commit()


def _load_preliminary_results(conn, election: dict, rng: random.Random) -> None:
    snapshot = SNAPSHOT_NIGHT
    for ao in election["afstemningsomraader"]:
        ok_id = ao["opstillingskreds_id"]
        for party in election["parties"]:
            votes = rng.randint(50, 2000)
            # Party-level result row
            conn.execute(
                "INSERT OR IGNORE INTO results (afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) VALUES (?,?,?,?,?,?)",
                (ao["id"], party["id"], None, votes, "preliminary", snapshot),
            )
            # Party votes aggregate
            conn.execute(
                "INSERT OR IGNORE INTO party_votes (opstillingskreds_id, party_id, votes, snapshot_at) VALUES (?,?,?,?)",
                (ok_id, party["id"], votes, snapshot),
            )
    conn.commit()


def _load_final_results(conn, election: dict, rng: random.Random) -> None:
    snapshot = SNAPSHOT_FINAL
    # Build a lookup: (opstillingskreds_id, party_id) -> candidates
    ok_party_candidates: dict[tuple, list] = {}
    for c in election["candidates"]:
        key = (c["opstillingskreds_id"], c["party_id"])
        ok_party_candidates.setdefault(key, []).append(c)

    for ao in election["afstemningsomraader"]:
        ok_id = ao["opstillingskreds_id"]
        for party in election["parties"]:
            candidates = ok_party_candidates.get((ok_id, party["id"]), [])
            for c in candidates:
                votes = rng.randint(10, 500)
                conn.execute(
                    "INSERT OR IGNORE INTO results (afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) VALUES (?,?,?,?,?,?)",
                    (ao["id"], party["id"], c["id"], votes, "final", snapshot),
                )
    conn.commit()


def _distribute(total: int, n: int, rng: random.Random) -> list[int]:
    """Distribute total across n buckets, each at least 1."""
    if n <= 0:
        return []
    cuts = sorted(rng.sample(range(1, total), min(n - 1, total - 1)))
    boundaries = [0] + cuts + [total]
    return [boundaries[i+1] - boundaries[i] for i in range(n)]
