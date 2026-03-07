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

TOTAL_SEATS = 175
KREDSMANDAT_SEATS = 135
TILLAEG_SEATS = 40
THRESHOLD_PCT = 0.02


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


def allocate_seats_total(
    national_votes: dict[str, int],
    storkreds_votes: dict[str, dict[str, int]],
    kredsmandater: dict[str, int],
) -> dict[str, int]:
    """
    Full seat allocation: kredsmandater (D'Hondt) + approx tillægsmandater (Saint-Laguë).

    Args:
        national_votes: {party_id: total_votes_nationally}
        storkreds_votes: {storkreds_id: {party_id: votes}}
        kredsmandater: {storkreds_id: n_seats}

    Returns:
        {party_id: total_projected_seats} for all parties (0 if below threshold)
    """
    kreds_won = allocate_kredsmandater(storkreds_votes, kredsmandater)
    qualifying = _apply_threshold(national_votes, kreds_won)
    qualifying_votes = {p: v for p, v in national_votes.items() if p in qualifying}
    national_seats = modified_saint_lague(qualifying_votes, TOTAL_SEATS)

    result = {p: 0 for p in national_votes}
    for party in qualifying:
        national = national_seats.get(party, 0)
        kreds = kreds_won.get(party, 0)
        tillaeg = max(0, national - kreds)
        result[party] = kreds + tillaeg

    return result


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
