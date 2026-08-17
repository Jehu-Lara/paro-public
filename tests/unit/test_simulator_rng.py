"""RNG substream derivation (docs/simulator-spec.md section 3).

Expected values below were computed independently (plain ``hashlib`` in a
throwaway shell, not by calling ``machine_seed`` itself) so this test can't
pass by construction if the implementation and the "expectation" share the
same bug.
"""

from scripts.simulator.rng import machine_rng, machine_seed


def test_machine_seed_matches_independently_computed_sha256() -> None:
    assert machine_seed(42, 1) == 278651779053087998
    assert machine_seed(42, 2) == 14840890843343779510
    assert machine_seed(1, 1) == 15471431920398990283


def test_machine_rng_is_deterministic_for_same_pair() -> None:
    first = machine_rng(42, 1)
    second = machine_rng(42, 1)

    assert [first.random() for _ in range(5)] == [second.random() for _ in range(5)]


def test_machine_rng_differs_across_machines() -> None:
    machine_1 = machine_rng(42, 1)
    machine_2 = machine_rng(42, 2)

    assert [machine_1.random() for _ in range(5)] != [machine_2.random() for _ in range(5)]
