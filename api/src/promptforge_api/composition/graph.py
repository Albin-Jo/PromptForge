"""Pure graph algorithms for prompt composition — no DB, no I/O (Sprint 10).

A composition is a directed graph of "X includes Y" edges. Two operations, both
generic over any hashable node id (a block id for the identity-level cycle guard, or a
block-version id for version-level resolve order), so the same tested code serves both:

- :func:`find_cycle` — DFS three-colouring. Detects a circular reference (ADR 0015) and
  returns the offending cycle as a path so the API can name it; ``None`` if acyclic.
- :func:`topological_sort` — orders nodes **dependencies-first** (every node comes after
  everything it includes), the order render resolution fills its memo in.

Implemented **iteratively** (explicit stacks/queues), not recursively, so a deep
include-chain can't blow Python's recursion limit. Adjacency is
``Mapping[node, Sequence[neighbour]]``; a node with no out-edges may be omitted or map
to an empty sequence, and duplicate edges are treated as one (the relation is a set).
"""

from collections.abc import Collection, Hashable, Iterator, Mapping, Sequence

# DFS node states for cycle detection: unseen, on the current path, fully explored.
_WHITE, _GREY, _BLACK = 0, 1, 2


class CompositionCycleError(Exception):
    """Raised when a composition graph contains a cycle (a circular reference)."""

    def __init__(self, cycle: Sequence[Hashable]) -> None:
        self.cycle = list(cycle)
        rendered = " -> ".join(str(node) for node in self.cycle)
        super().__init__(f"circular reference: {rendered}")


def _all_nodes[T: Hashable](adjacency: Mapping[T, Collection[T]]) -> list[T]:
    """Every node that appears as a key or as a neighbour, first-seen order.

    Neighbours that are never keys (leaf dependencies with no out-edges) still have to
    be visited, so we can't just iterate the keys. A dict preserves insertion order and
    dedupes, giving a deterministic node set.
    """
    seen: dict[T, None] = {}
    for node, neighbours in adjacency.items():
        seen.setdefault(node, None)
        for neighbour in neighbours:
            seen.setdefault(neighbour, None)
    return list(seen)


def find_cycle[T: Hashable](adjacency: Mapping[T, Collection[T]]) -> list[T] | None:
    """Return a cycle as a path ``[n0, …, n0]`` if one exists, else ``None``.

    Iterative depth-first search with three colours: a node is **grey** while it sits on
    the current DFS path and **black** once fully explored. Reaching a **grey** node means
    an edge points back into the current path — a cycle — and the slice of the path from
    that node to the present, closed back onto it, *is* the cycle (a self-loop yields
    ``[n, n]``). Black nodes are skipped: they've been cleared and can't start a new cycle.
    """
    colour: dict[T, int] = dict.fromkeys(_all_nodes(adjacency), _WHITE)

    for start in colour:
        if colour[start] != _WHITE:
            continue
        # Each stack frame keeps its own neighbour iterator, so when we pop back to a
        # parent we resume exactly where we left off. `path` mirrors the grey frames.
        stack: list[tuple[T, Iterator[T]]] = [(start, iter(adjacency.get(start, ())))]
        path: list[T] = [start]
        colour[start] = _GREY
        while stack:
            node, neighbours = stack[-1]
            descended = False
            for neighbour in neighbours:
                if colour[neighbour] == _GREY:
                    return path[path.index(neighbour) :] + [neighbour]
                if colour[neighbour] == _WHITE:
                    colour[neighbour] = _GREY
                    stack.append((neighbour, iter(adjacency.get(neighbour, ()))))
                    path.append(neighbour)
                    descended = True
                    break  # recurse into the child before the rest of node's edges
            if not descended:
                colour[node] = _BLACK
                stack.pop()
                path.pop()
    return None


def topological_sort[T: Hashable](adjacency: Mapping[T, Collection[T]]) -> list[T]:
    """Order nodes dependencies-first; raise :class:`CompositionCycleError` on a cycle.

    Kahn's algorithm run on the *includes* graph by **out-degree**: a node that includes
    nothing (out-degree 0) is a leaf dependency and is emitted first; emitting it
    decrements the out-degree of everything that included it, and a parent is emitted once
    all the things it includes have been. The result is the order to resolve a composition
    — every block appears after the blocks it pulls in. If some nodes never reach
    out-degree 0, the graph has a cycle and we surface the path from :func:`find_cycle`.
    """
    nodes = _all_nodes(adjacency)
    # Dedupe edges: the dependency relation is a set, so "includes B twice" is one edge
    # for ordering purposes (assembly order is handled separately, by position).
    out_neighbours: dict[T, set[T]] = {n: set(adjacency.get(n, ())) for n in nodes}
    out_degree: dict[T, int] = {n: len(out_neighbours[n]) for n in nodes}
    # Reverse edges: for each child, who includes it — so emitting a child can notify them.
    includers: dict[T, list[T]] = {n: [] for n in nodes}
    for node in nodes:
        for child in out_neighbours[node]:
            includers[child].append(node)

    ready = [n for n in nodes if out_degree[n] == 0]
    order: list[T] = []
    while ready:
        node = ready.pop()
        order.append(node)
        for parent in includers[node]:
            out_degree[parent] -= 1
            if out_degree[parent] == 0:
                ready.append(parent)

    if len(order) != len(nodes):
        cycle = find_cycle(adjacency)
        raise CompositionCycleError(cycle if cycle is not None else [])
    return order
