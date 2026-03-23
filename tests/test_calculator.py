# tests/test_calculator.py
import pytest
from valg.calculator import (
    dhondt,
    modified_saint_lague,
    allocate_kredsmandater,
    allocate_seats_total,
    votes_to_gain_seat,
    votes_to_lose_seat,
    constituency_flip_feasibility,
    seat_momentum,
)

# --- dhondt ---

def test_dhondt_equal_votes_splits_evenly():
    assert dhondt({"A": 1000, "B": 1000}, 4) == {"A": 2, "B": 2}

def test_dhondt_proportional_three_to_one():
    result = dhondt({"A": 3000, "B": 1000}, 4)
    assert result == {"A": 3, "B": 1}

def test_dhondt_single_party_gets_all():
    assert dhondt({"A": 5000}, 5) == {"A": 5}

def test_dhondt_zero_votes_gets_zero_seats():
    result = dhondt({"A": 1000, "B": 0}, 4)
    assert result["B"] == 0
    assert result["A"] == 4

def test_dhondt_returns_all_parties():
    result = dhondt({"A": 1000, "B": 500, "C": 100}, 3)
    assert set(result.keys()) == {"A", "B", "C"}

def test_dhondt_total_seats_equals_n():
    result = dhondt({"A": 3000, "B": 2000, "C": 1000}, 7)
    assert sum(result.values()) == 7

# --- modified_saint_lague ---

def test_saint_lague_equal_votes():
    assert modified_saint_lague({"A": 1000, "B": 1000}, 4) == {"A": 2, "B": 2}

def test_saint_lague_first_divisor_14_favours_larger_party():
    result = modified_saint_lague({"A": 1000, "B": 500}, 3)
    assert result["A"] >= result["B"]

def test_saint_lague_total_seats_equals_n():
    result = modified_saint_lague({"A": 3000, "B": 2000, "C": 1000}, 7)
    assert sum(result.values()) == 7

def test_saint_lague_returns_all_parties():
    result = modified_saint_lague({"A": 1000, "B": 500}, 4)
    assert set(result.keys()) == {"A", "B"}

def test_saint_lague_zero_votes_gets_zero():
    result = modified_saint_lague({"A": 1000, "B": 0}, 3)
    assert result["B"] == 0

# --- allocate_kredsmandater ---

def test_allocate_kredsmandater_sums_correctly():
    storkreds_votes = {
        "SK1": {"A": 1000, "B": 500},
        "SK2": {"A": 800, "B": 700},
    }
    kredsmandater = {"SK1": 5, "SK2": 5}
    result = allocate_kredsmandater(storkreds_votes, kredsmandater)
    # result is {party: total_kredsmandater}
    assert sum(result.values()) == 10

def test_allocate_kredsmandater_returns_all_parties():
    storkreds_votes = {"SK1": {"A": 1000, "B": 500}}
    result = allocate_kredsmandater(storkreds_votes, {"SK1": 3})
    assert "A" in result and "B" in result

# --- allocate_seats_total ---

def test_allocate_seats_total_sums_to_175_or_less():
    national_votes = {"A": 50000, "B": 30000, "C": 20000, "D": 5000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000, "D": 5000}}
    kredsmandater = {"SK1": 135}
    result = allocate_seats_total(national_votes, storkreds_votes, kredsmandater)
    assert sum(result.values()) <= 175

def test_allocate_seats_total_threshold_excludes_small_party():
    # Party D has less than 2% of total — should get 0 seats
    total = 100000
    national_votes = {"A": 50000, "B": 30000, "C": 18000, "D": 2000}  # D = 2%, boundary
    storkreds_votes = {"SK1": national_votes}
    kredsmandater = {"SK1": 135}
    result = allocate_seats_total(national_votes, storkreds_votes, kredsmandater)
    assert isinstance(result, dict)
    assert set(result.keys()) == {"A", "B", "C", "D"}

def test_allocate_seats_total_returns_all_parties():
    national_votes = {"A": 50000, "B": 30000}
    result = allocate_seats_total(national_votes, {"SK1": {"A": 50000, "B": 30000}}, {"SK1": 10})
    assert "A" in result and "B" in result

# --- votes_to_gain_seat / votes_to_lose_seat ---

def test_votes_to_gain_seat_returns_positive_int():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 10}
    delta = votes_to_gain_seat("A", national_votes, storkreds_votes, kredsmandater)
    assert isinstance(delta, int)
    assert delta > 0

def test_votes_to_lose_seat_returns_positive_int():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 10}
    delta = votes_to_lose_seat("A", national_votes, storkreds_votes, kredsmandater)
    assert isinstance(delta, int)
    assert delta > 0

def test_adding_votes_to_gain_seat_increases_seats():
    national_votes = {"A": 50000, "B": 30000, "C": 20000}
    storkreds_votes = {"SK1": {"A": 50000, "B": 30000, "C": 20000}}
    kredsmandater = {"SK1": 10}
    before = allocate_seats_total(national_votes, storkreds_votes, kredsmandater)["A"]
    delta = votes_to_gain_seat("A", national_votes, storkreds_votes, kredsmandater)
    new_votes = dict(national_votes)
    new_votes["A"] += delta
    new_sk = {"SK1": dict(storkreds_votes["SK1"])}
    new_sk["SK1"]["A"] += delta
    after = allocate_seats_total(new_votes, new_sk, kredsmandater)["A"]
    assert after > before

# --- constituency_flip_feasibility ---

def test_flip_feasibility_feasible_when_gap_small():
    result = constituency_flip_feasibility(
        leader_votes=1000,
        challenger_votes=900,
        uncounted_eligible_voters=500,
        historical_turnout_rate=0.8,
    )
    assert result["feasible"] is True
    assert result["gap"] == 100

def test_flip_feasibility_infeasible_when_gap_large():
    result = constituency_flip_feasibility(
        leader_votes=1000,
        challenger_votes=100,
        uncounted_eligible_voters=200,
        historical_turnout_rate=0.5,
    )
    assert result["feasible"] is False

def test_flip_feasibility_returns_max_remaining():
    result = constituency_flip_feasibility(
        leader_votes=1000,
        challenger_votes=900,
        uncounted_eligible_voters=500,
        historical_turnout_rate=0.8,
    )
    assert result["max_remaining"] == 400  # 500 * 0.8

# --- seat_momentum ---

def test_seat_momentum_positive_when_gaining_votes():
    result = seat_momentum("A", votes_before=1000, votes_after=1500)
    assert result > 0

def test_seat_momentum_negative_when_losing_votes():
    result = seat_momentum("A", votes_before=1500, votes_after=1000)
    assert result < 0

def test_seat_momentum_zero_when_unchanged():
    result = seat_momentum("A", votes_before=1000, votes_after=1000)
    assert result == 0


# --- hare_largest_remainder ---

from valg.calculator import hare_largest_remainder

def test_hare_basic_proportional():
    result = hare_largest_remainder({"A": 60, "B": 40}, 10)
    assert result == {"A": 6, "B": 4}

def test_hare_remainder_allocation():
    result = hare_largest_remainder({"A": 50, "B": 30, "C": 20}, 3)
    assert result == {"A": 1, "B": 1, "C": 1}

def test_hare_total_seats():
    result = hare_largest_remainder({"A": 971995, "B": 470546, "C": 327699}, 175)
    assert sum(result.values()) == 175

def test_hare_zero_votes():
    result = hare_largest_remainder({"A": 1000, "B": 0}, 5)
    assert result["B"] == 0
    assert result["A"] == 5

def test_hare_empty():
    result = hare_largest_remainder({}, 10)
    assert result == {}


# --- allocate_kredsmandater_detail ---

from valg.calculator import allocate_kredsmandater_detail

def test_kredsmandater_detail_returns_per_storkreds():
    storkreds_votes = {
        "SK1": {"A": 3000, "B": 1000},
        "SK2": {"A": 800, "B": 700},
    }
    kredsmandater = {"SK1": 4, "SK2": 3}
    result = allocate_kredsmandater_detail(storkreds_votes, kredsmandater)
    assert "SK1" in result and "SK2" in result
    assert sum(result["SK1"].values()) == 4
    assert sum(result["SK2"].values()) == 3

def test_kredsmandater_detail_matches_existing_totals():
    storkreds_votes = {
        "SK1": {"A": 3000, "B": 1000, "C": 500},
        "SK2": {"A": 800, "B": 700, "C": 600},
    }
    kredsmandater = {"SK1": 5, "SK2": 4}
    detail = allocate_kredsmandater_detail(storkreds_votes, kredsmandater)
    old_totals = allocate_kredsmandater(storkreds_votes, kredsmandater)
    new_totals = {}
    for sk_seats in detail.values():
        for party, s in sk_seats.items():
            new_totals[party] = new_totals.get(party, 0) + s
    assert new_totals == old_totals


# --- landsdel mapping + allocate_tillaeg_to_landsdele ---

from valg.calculator import allocate_tillaeg_to_landsdele, LANDSDEL_STORKREDSE

def test_landsdel_mapping_covers_all_10_storkredse():
    all_sk = set()
    for sks in LANDSDEL_STORKREDSE.values():
        all_sk.update(sks)
    assert len(all_sk) == 10
    assert len(LANDSDEL_STORKREDSE) == 3

def test_tillaeg_landsdele_basic():
    party_landsdel_votes = {"A": {"LD1": 1000}, "B": {"LD1": 800}}
    tillaeg_per_party = {"A": 1, "B": 2}
    kreds_per_party_per_landsdel = {"A": {"LD1": 2}, "B": {"LD1": 0}}
    result = allocate_tillaeg_to_landsdele(party_landsdel_votes, tillaeg_per_party, kreds_per_party_per_landsdel)
    assert sum(result["A"].values()) == 1
    assert sum(result["B"].values()) == 2

def test_tillaeg_landsdele_total():
    party_landsdel_votes = {
        "A": {"LD1": 50000, "LD2": 30000, "LD3": 20000},
        "B": {"LD1": 20000, "LD2": 25000, "LD3": 15000},
    }
    tillaeg_per_party = {"A": 5, "B": 8}
    kreds_per_party_per_landsdel = {
        "A": {"LD1": 3, "LD2": 2, "LD3": 1},
        "B": {"LD1": 1, "LD2": 1, "LD3": 0},
    }
    result = allocate_tillaeg_to_landsdele(party_landsdel_votes, tillaeg_per_party, kreds_per_party_per_landsdel)
    total = sum(s for party_ld in result.values() for s in party_ld.values())
    assert total == 13
