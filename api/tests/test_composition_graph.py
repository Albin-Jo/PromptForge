"""Unit tests for the pure composition graph algorithms (no DB, no I/O).

The classic time-sinks for cycle detection are crafted here on purpose: a
**self-reference**, a **diamond** (shared dependency that is *not* a cycle), a
**deep chain** (would overflow a recursive implementation), **disconnected**
components, and a valid DAG. Topological order is checked by its defining property —
every node appears after everything it includes — rather than an exact sequence,
since any dependencies-first ordering is correct.
"""

from collections.abc import Mapping, Sequence

import pytest

from promptforge_api.composition.graph import (
    CompositionCycleError,
    find_cycle,
    topological_sort,
)


def _is_cycle(adjacency: Mapping[str, Sequence[str]], path: list[str]) -> bool:
    """A returned path is a real cycle: it closes on itself and each hop is an edge."""
    if len(path) < 2 or path[0] != path[-1]:
        return False
    return all(path[i + 1] in adjacency.get(path[i], ()) for i in range(len(path) - 1))


def _assert_topo_valid(adjacency: Mapping[str, Sequence[str]], order: list[str]) -> None:
    """Every node comes after everything it includes (dependencies first)."""
    position = {node: i for i, node in enumerate(order)}
    for node, children in adjacency.items():
        for child in children:
            assert position[child] < position[node], f"{child} must precede {node}"


# ----------------------------------------------------------------- find_cycle


def test_empty_graph_has_no_cycle() -> None:
    assert find_cycle({}) is None


def test_single_node_no_edges() -> None:
    assert find_cycle({"a": []}) is None


def test_self_reference_is_a_cycle() -> None:
    cycle = find_cycle({"a": ["a"]})
    assert cycle == ["a", "a"]


def test_two_node_cycle() -> None:
    adjacency = {"a": ["b"], "b": ["a"]}
    cycle = find_cycle(adjacency)
    assert cycle is not None
    assert _is_cycle(adjacency, cycle)
    assert set(cycle) == {"a", "b"}


def test_diamond_is_not_a_cycle() -> None:
    """A shared dependency reached two ways is a DAG, not a cycle — the classic trap."""
    diamond = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    assert find_cycle(diamond) is None


def test_deep_chain_is_acyclic_then_closed_into_a_cycle() -> None:
    chain = {f"n{i}": [f"n{i + 1}"] for i in range(1000)}
    chain["n1000"] = []
    assert find_cycle(chain) is None

    chain["n1000"] = ["n0"]  # close the loop
    cycle = find_cycle(chain)
    assert cycle is not None
    assert _is_cycle(chain, cycle)
    assert len(cycle) == 1002  # n0 -> n1 -> … -> n1000 -> n0


def test_cycle_found_among_disconnected_components() -> None:
    graph = {
        "x": ["y"],  # clean component
        "y": [],
        "p": ["q"],  # component with a cycle
        "q": ["r"],
        "r": ["p"],
    }
    cycle = find_cycle(graph)
    assert cycle is not None
    assert _is_cycle(graph, cycle)
    assert set(cycle) == {"p", "q", "r"}


def test_node_only_referenced_as_neighbour_is_visited() -> None:
    """'d' is never a key; it still must be explored (no false cycle, no KeyError)."""
    assert find_cycle({"a": ["b"], "b": ["c", "d"], "c": []}) is None


# ------------------------------------------------------------- topological_sort


def test_topological_sort_orders_dependencies_first() -> None:
    diamond = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
    order = topological_sort(diamond)
    assert len(order) == 4
    assert set(order) == {"a", "b", "c", "d"}
    _assert_topo_valid(diamond, order)
    # the shared leaf resolves first, the root last
    assert order[0] == "d"
    assert order[-1] == "a"


def test_topological_sort_of_a_chain() -> None:
    chain = {f"n{i}": [f"n{i + 1}"] for i in range(50)}
    chain["n50"] = []
    order = topological_sort(chain)
    assert len(order) == 51
    _assert_topo_valid(chain, order)


def test_topological_sort_includes_neighbour_only_nodes() -> None:
    graph = {"a": ["b"], "b": ["c"]}  # 'c' only appears as a neighbour
    order = topological_sort(graph)
    assert set(order) == {"a", "b", "c"}
    _assert_topo_valid(graph, order)


def test_topological_sort_dedupes_repeated_edges() -> None:
    """Including the same child twice (e.g. two positions) is one edge for ordering."""
    graph = {"a": ["b", "b"], "b": []}
    order = topological_sort(graph)
    assert order == ["b", "a"]


def test_topological_sort_raises_on_cycle() -> None:
    with pytest.raises(CompositionCycleError) as exc:
        topological_sort({"a": ["b"], "b": ["a"]})
    # the error names the offending cycle
    assert "circular reference" in str(exc.value)
    assert set(exc.value.cycle) == {"a", "b"}


def test_topological_sort_raises_on_self_loop() -> None:
    with pytest.raises(CompositionCycleError):
        topological_sort({"a": ["a"]})
