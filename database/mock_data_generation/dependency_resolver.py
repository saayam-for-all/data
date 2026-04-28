"""Resolve table generation order using foreign keys."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Set

from .schema_parser import ParsedSchema


def resolve_generation_order(schema: ParsedSchema, selected_tables: List[str]) -> List[str]:
    selected = set(selected_tables)
    indegree: Dict[str, int] = {table: 0 for table in selected}
    graph: Dict[str, Set[str]] = defaultdict(set)

    for table_name in selected:
        table = schema.require_table(table_name)
        for _, fk_reference in table.foreign_keys.items():
            fk_table = fk_reference.split(".", maxsplit=1)[0]
            if fk_table in selected and table_name not in graph[fk_table]:
                graph[fk_table].add(table_name)
                indegree[table_name] += 1

    queue = deque(sorted([table for table, degree in indegree.items() if degree == 0]))
    ordered: List[str] = []

    while queue:
        current = queue.popleft()
        ordered.append(current)
        for neighbor in sorted(graph.get(current, set())):
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0:
                queue.append(neighbor)

    if len(ordered) != len(selected):
        unresolved = sorted(selected - set(ordered))
        raise ValueError(f"Cycle or unresolved dependency detected: {unresolved}")

    return ordered
