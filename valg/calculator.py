# valg/calculator.py
"""
Pure-function seat calculator for Danish Folketing elections.

All functions take plain dicts as input and return plain dicts or scalars.
No I/O, no database access.

Seat allocation:
  - kredsmandater (135): D'Hondt per storkreds
  - tillægsmandater (40): approximated via national modified Saint-Laguë minus kredsmandater
  - Threshold: party needs >= 2% nationally, OR >= 1 kredsmandat
"""
from __future__ import annotations

import heapq

TURNOUT_ESTIMATE = 0.84

TOTAL_SEATS = 175
KREDSMANDAT_SEATS = 135
TILLAEG_SEATS = 40
THRESHOLD_PCT = 0.02

LANDSDEL_STORKREDSE = {
    "Hovedstaden": ["1", "2", "3", "4"],
    "Sjaelland-Syddanmark": ["5", "6", "7"],
    "Midtjylland-Nordjylland": ["8", "9", "10"],
}
STORKREDS_TO_LANDSDEL = {
    sk: ld for ld, sks in LANDSDEL_STORKREDSE.items() for sk in sks
}


def dhondt(party_votes: dict[str, int], n_seats: int) -> dict[str, int]:
    """
    Allocate n_seats using the D'Hondt method.

    Args:
        party_votes: {party_id: votes}
        n_seats: number of seats to allocate

    Returns:
        {party_id: seats_allocated}
    """
    seats = {p: 0 for p in party_votes}
    if n_seats <= 0:
        return seats

    heap = [(-votes, party) for party, votes in party_votes.items() if votes > 0]
    heapq.heapify(heap)

    for _ in range(n_seats):
        if not heap:
            break
        neg_quotient, party = heapq.heappop(heap)
        seats[party] += 1
        new_votes = party_votes[party] / (seats[party] + 1)
        heapq.heappush(heap, (-new_votes, party))

    return seats


def modified_saint_lague(party_votes: dict[str, int], n_seats: int) -> dict[str, int]:
    """
    Allocate n_seats using modified Saint-Laguë (first divisor 1.4).

    Args:
        party_votes: {party_id: votes}
        n_seats: number of seats to allocate

    Returns:
        {party_id: seats_allocated}
    """
    seats = {p: 0 for p in party_votes}
    if n_seats <= 0:
        return seats

    def divisor(n: int) -> float:
        return 1.4 if n == 0 else (2 * n + 1)

    heap = [(-votes / divisor(0), party) for party, votes in party_votes.items() if votes > 0]
    heapq.heapify(heap)

    for _ in range(n_seats):
        if not heap:
            break
        _, party = heapq.heappop(heap)
        seats[party] += 1
        new_quotient = party_votes[party] / divisor(seats[party])
        heapq.heappush(heap, (-new_quotient, party))

    return seats


def allocate_kredsmandater(
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, int]:
    """
    Allocate kredsmandater for each storkreds using D'Hondt.

    Args:
        storkreds_votes: {storkreds_id: {party_id: votes}}
        kredsmandater: {storkreds_id: n_seats}

    Returns:
        {party_id: total_kredsmandater} across all storkredse
    """
    totals: dict[str, int] = {}
    for sk_id, votes in storkreds_votes.items():
        n = kredsmandater.get(sk_id, 0)
        if n <= 0:
            continue
        allocated = dhondt(votes, n)
        for party, s in allocated.items():
            totals[party] = totals.get(party, 0) + s
    return totals


def _apply_threshold(
    national_votes: dict[str, int],
    kredsmandater_won: dict[str, int],
) -> set[str]:
    """Return the set of party IDs that pass the threshold."""
    total = sum(national_votes.values())
    if total == 0:
        return set()
    qualifying = set()
    for party, votes in national_votes.items():
        pct = votes / total
        kreds = kredsmandater_won.get(party, 0)
        if pct >= THRESHOLD_PCT or kreds >= 1:
            qualifying.add(party)
    return qualifying


def allocate_seats_detail(
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, dict]:
    all_parties = set(national_votes.keys())

    # Step 1 (§76): kredsmandater per storkreds via D'Hondt
    kreds_detail = allocate_kredsmandater_detail(storkreds_votes, kredsmandater)

    # Sum kreds per party
    kreds_per_party: dict[str, int] = {}
    kreds_by_storkreds: dict[str, dict[str, int]] = {}
    for sk, sk_seats in kreds_detail.items():
        for party, s in sk_seats.items():
            kreds_per_party[party] = kreds_per_party.get(party, 0) + s
            kreds_by_storkreds.setdefault(party, {})[sk] = \
                kreds_by_storkreds.get(party, {}).get(sk, 0) + s

    # Qualifying (§76 threshold)
    qualifying = _apply_threshold(national_votes, kreds_per_party)

    # Step 2 (§77): Hare largest remainder for TOTAL_SEATS
    # Overhang loop (§77 stk. 4-5)
    overhang_parties: set[str] = set()
    remaining_seats = TOTAL_SEATS
    while True:
        eligible = {p: v for p, v in national_votes.items()
                    if p in qualifying and p not in overhang_parties}
        hare_seats = hare_largest_remainder(eligible, remaining_seats)

        new_overhang = False
        for party, seats in hare_seats.items():
            kreds = kreds_per_party.get(party, 0)
            if kreds > seats:  # strict >
                overhang_parties.add(party)
                remaining_seats -= kreds
                new_overhang = True

        if not new_overhang:
            break

    # Tillaeg per party
    tillaeg_per_party: dict[str, int] = {}
    for party in qualifying:
        if party in overhang_parties:
            tillaeg_per_party[party] = 0
        else:
            tillaeg_per_party[party] = max(0, hare_seats.get(party, 0) - kreds_per_party.get(party, 0))

    # Step 3 (§78): landsdel tillaeg allocation
    # Build landsdel votes by summing storkreds votes
    party_landsdel_votes: dict[str, dict[str, int]] = {}
    kreds_per_party_per_landsdel: dict[str, dict[str, int]] = {}
    kreds_per_party_per_storkreds: dict[str, dict[str, int]] = {}
    for sk, sk_votes in storkreds_votes.items():
        ld = STORKREDS_TO_LANDSDEL.get(sk)
        if ld is None:
            continue
        for party, votes in sk_votes.items():
            party_landsdel_votes.setdefault(party, {})
            party_landsdel_votes[party][ld] = party_landsdel_votes[party].get(ld, 0) + votes

    for sk, sk_seats in kreds_detail.items():
        ld = STORKREDS_TO_LANDSDEL.get(sk)
        for party, s in sk_seats.items():
            kreds_per_party_per_landsdel.setdefault(party, {})
            kreds_per_party_per_landsdel[party][ld] = \
                kreds_per_party_per_landsdel[party].get(ld, 0) + s
            kreds_per_party_per_storkreds.setdefault(party, {})
            kreds_per_party_per_storkreds[party][sk] = \
                kreds_per_party_per_storkreds[party].get(sk, 0) + s

    # Only pass qualifying parties with tillaeg > 0
    tillaeg_qualifying = {p: t for p, t in tillaeg_per_party.items() if t > 0}
    ld_votes_qualifying = {p: v for p, v in party_landsdel_votes.items() if p in tillaeg_qualifying}
    kreds_ld_qualifying = {p: v for p, v in kreds_per_party_per_landsdel.items() if p in tillaeg_qualifying}

    tillaeg_by_landsdel = allocate_tillaeg_to_landsdele(
        ld_votes_qualifying, tillaeg_qualifying, kreds_ld_qualifying,
    )

    # Step 4 (§79): storkreds tillaeg allocation
    sk_votes_qualifying = {p: {sk: v for sk, v in storkreds_votes_for_party(storkreds_votes, p).items()}
                           for p in tillaeg_qualifying}
    kreds_sk_qualifying = {p: v for p, v in kreds_per_party_per_storkreds.items() if p in tillaeg_qualifying}

    tillaeg_by_storkreds_result = allocate_tillaeg_to_storkredse(
        sk_votes_qualifying, tillaeg_by_landsdel,
        kreds_sk_qualifying, LANDSDEL_STORKREDSE,
    )

    # Assemble result
    result: dict[str, dict] = {}
    for party in all_parties:
        kreds = kreds_per_party.get(party, 0)
        tillaeg = tillaeg_per_party.get(party, 0)
        result[party] = {
            "kreds": kreds,
            "tillaeg": tillaeg,
            "total": kreds + tillaeg,
            "kreds_by_storkreds": kreds_by_storkreds.get(party, {}),
            "tillaeg_by_storkreds": tillaeg_by_storkreds_result.get(party, {}),
        }

    return result


def storkreds_votes_for_party(
    storkreds_votes: dict[str, dict[str, int]], party: str,
) -> dict[str, int]:
    return {sk: votes.get(party, 0) for sk, votes in storkreds_votes.items()}


def allocate_seats_total(
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, int]:
    detail = allocate_seats_detail(national_votes, storkreds_votes, kredsmandater)
    return {party: d["total"] for party, d in detail.items()}


def votes_to_gain_seat(
    party: str,
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
    max_search: int = 500_000,
) -> int:
    """
    Find the minimum additional votes for `party` to gain one seat.
    Uses binary search. Returns max_search if no gain found in range.
    """
    current_seats = allocate_seats_total(national_votes, storkreds_votes, kredsmandater).get(party, 0)

    def seats_with_delta(delta: int) -> int:
        new_national = dict(national_votes)
        new_national[party] = new_national.get(party, 0) + delta
        new_storkreds = {sk: dict(v) for sk, v in storkreds_votes.items()}
        for sk_votes in new_storkreds.values():
            if party in sk_votes:
                sk_votes[party] += delta
                break
        return allocate_seats_total(new_national, new_storkreds, kredsmandater).get(party, 0)

    lo, hi = 1, max_search
    while lo < hi:
        mid = (lo + hi) // 2
        if seats_with_delta(mid) > current_seats:
            hi = mid
        else:
            lo = mid + 1
    return lo


def votes_to_lose_seat(
    party: str,
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
    max_search: int = 500_000,
) -> int:
    """
    Find the minimum votes `party` can lose before losing a seat.
    Returns max_search if no loss found in range.
    """
    current_seats = allocate_seats_total(national_votes, storkreds_votes, kredsmandater).get(party, 0)
    current_votes = national_votes.get(party, 0)

    def seats_with_loss(delta: int) -> int:
        new_national = dict(national_votes)
        new_national[party] = max(0, current_votes - delta)
        new_storkreds = {sk: dict(v) for sk, v in storkreds_votes.items()}
        for sk_votes in new_storkreds.values():
            if party in sk_votes:
                sk_votes[party] = max(0, sk_votes[party] - delta)
                break
        return allocate_seats_total(new_national, new_storkreds, kredsmandater).get(party, 0)

    lo, hi = 1, min(max_search, current_votes)
    if hi <= 0:
        return 1
    while lo < hi:
        mid = (lo + hi) // 2
        if seats_with_loss(mid) < current_seats:
            hi = mid
        else:
            lo = mid + 1
    return lo


def constituency_flip_feasibility(
    leader_votes: int,
    challenger_votes: int,
    uncounted_eligible_voters: int,
    historical_turnout_rate: float,
) -> dict:
    """
    Can the challenger overtake the leader given remaining uncounted votes?

    Returns:
        {feasible: bool, gap: int, max_remaining: int}
    """
    gap = leader_votes - challenger_votes
    max_remaining = int(uncounted_eligible_voters * historical_turnout_rate)
    return {
        "feasible": gap < max_remaining,
        "gap": gap,
        "max_remaining": max_remaining,
    }


def seat_momentum(party: str, votes_before: int, votes_after: int) -> int:
    """Return vote delta (positive = gaining, negative = losing)."""
    return votes_after - votes_before


def allocate_kredsmandater_detail(
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, dict[str, int]]:
    result = {}
    for sk_id, votes in storkreds_votes.items():
        n = kredsmandater.get(sk_id, 0)
        if n <= 0:
            result[sk_id] = {p: 0 for p in votes}
            continue
        result[sk_id] = dhondt(votes, n)
    return result


def hare_largest_remainder(party_votes: dict[str, int], n_seats: int) -> dict[str, int]:
    if not party_votes or n_seats <= 0:
        return {p: 0 for p in party_votes}

    total = sum(party_votes.values())
    if total == 0:
        return {p: 0 for p in party_votes}

    quota = total / n_seats
    seats = {}
    remainders = {}
    for party, votes in party_votes.items():
        full = int(votes // quota) if votes > 0 else 0
        seats[party] = full
        remainders[party] = (votes / quota) - full if votes > 0 else 0.0

    allocated = sum(seats.values())
    remaining = n_seats - allocated
    ranked = sorted(remainders, key=lambda p: -remainders[p])
    for i in range(remaining):
        seats[ranked[i]] += 1

    return seats


def allocate_tillaeg_to_landsdele(
    party_landsdel_votes: dict[str, dict[str, int]],
    tillaeg_per_party: dict[str, int],
    kreds_per_party_per_landsdel: dict[str, dict[str, int]],
) -> dict[str, dict[str, int]]:
    total_tillaeg = sum(tillaeg_per_party.values())
    if total_tillaeg <= 0:
        return {p: {} for p in tillaeg_per_party}

    # Build max-heap of Sainte-Lague quotients (1, 3, 5, 7...)
    # Skip first k quotients where k = kredsmandater already won
    heap = []
    # Track how many seats each party has been given
    party_given = {p: 0 for p in tillaeg_per_party}
    # Result structure
    result = {p: {} for p in tillaeg_per_party}

    max_quotients = total_tillaeg + max(
        sum(ld.values()) for ld in kreds_per_party_per_landsdel.values()
    ) if kreds_per_party_per_landsdel else total_tillaeg

    for party, ld_votes in party_landsdel_votes.items():
        if tillaeg_per_party.get(party, 0) <= 0:
            continue
        for ld, votes in ld_votes.items():
            if votes <= 0:
                continue
            k = kreds_per_party_per_landsdel.get(party, {}).get(ld, 0)
            # Generate enough quotients: skip first k, need up to tillaeg_per_party[party] more
            for n in range(k, k + tillaeg_per_party[party]):
                divisor = 2 * n + 1
                quotient = votes / divisor
                # max-heap via negation
                heapq.heappush(heap, (-quotient, party, ld))

    seats_given = 0
    while seats_given < total_tillaeg and heap:
        neg_q, party, ld = heapq.heappop(heap)
        if party_given[party] >= tillaeg_per_party[party]:
            continue
        party_given[party] += 1
        result[party][ld] = result[party].get(ld, 0) + 1
        seats_given += 1

    return result


def allocate_tillaeg_to_storkredse(
    party_storkreds_votes: dict[str, dict[str, int]],
    tillaeg_per_party_per_landsdel: dict[str, dict[str, int]],
    kreds_per_party_per_storkreds: dict[str, dict[str, int]],
    landsdel_storkredse: dict[str, list[str]],
) -> dict[str, dict[str, int]]:
    result = {p: {} for p in party_storkreds_votes}

    for party, ld_seats in tillaeg_per_party_per_landsdel.items():
        party_votes = party_storkreds_votes.get(party, {})
        party_kreds = kreds_per_party_per_storkreds.get(party, {})

        for ld, n_tillaeg in ld_seats.items():
            if n_tillaeg <= 0:
                continue
            storkredse = landsdel_storkredse.get(ld, [])
            if not storkredse:
                continue

            # Danish method divisors: 1, 4, 7, 10... (1 + 3*n)
            # Skip first k quotients per storkreds (kredsmandater already won)
            heap = []
            for sk in storkredse:
                votes = party_votes.get(sk, 0)
                if votes <= 0:
                    continue
                k = party_kreds.get(sk, 0)
                for n in range(k, k + n_tillaeg):
                    divisor = 1 + 3 * n
                    heapq.heappush(heap, (-votes / divisor, sk))

            given = 0
            while given < n_tillaeg and heap:
                _, sk = heapq.heappop(heap)
                result[party][sk] = result[party].get(sk, 0) + 1
                given += 1

    return result


def project_storkreds_votes(
    storkreds_votes: dict[str, dict[str, int]],
    reporting_progress: dict[str, float],
) -> dict[str, dict[str, int]]:
    result = {}
    for sk_id, party_votes in storkreds_votes.items():
        progress = reporting_progress.get(sk_id, 0.0)
        if progress <= 0:
            result[sk_id] = {p: 0 for p in party_votes}
        elif progress >= 1.0:
            result[sk_id] = dict(party_votes)
        else:
            result[sk_id] = {p: int(v / progress) for p, v in party_votes.items()}
    return result
