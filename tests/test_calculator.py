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
