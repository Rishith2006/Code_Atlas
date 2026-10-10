"""Call graphs, module dependencies and flow-to-function navigation."""
from __future__ import annotations

from collections import defaultdict, deque

from .parser import Project


class CallGraph:
    """Project-wide function call graph with heuristic name resolution."""

    def __init__(self, project: Project):
        self.project = project
        self.nodes: dict[str, object] = {f.qualified_name: f
                                         for f in project.all_functions()}
        self.edges: dict[str, set[str]] = defaultdict(set)   # caller -> callees
        self.reverse: dict[str, set[str]] = defaultdict(set)  # callee -> callers
        self._build()

    # -- resolution ------------------------------------------------------ #
    def _resolve(self, raw: str, caller_qname: str) -> str | None:
        """Map a raw call name (e.g. 'save', 'self.save', 'utils.parse') to a
        qualified project function, or None if it is external/builtin."""
        if not raw or raw.startswith("<"):
            return None
        short = raw.split(".")[-1]
        if short in {"self", "cls"}:
            return None
        caller_mod = ".".join(caller_qname.split(".")[:-1])

        cands = []
        for q in self.nodes:
            qshort = q.split(".")[-1]
            if q == raw or qshort == short:
                cands.append(q)
        if not cands:
            return None
        # Prefer same-module, then shortest (least nested) match.
        cands.sort(key=lambda q: (
            0 if q.startswith(caller_mod + ".") or q.rsplit(".", 1)[0] == caller_mod else 1,
            q.count("."), q))
        return cands[0]

    def _build(self):
        for qname, func in self.nodes.items():
            for raw in func.calls:
                target = self._resolve(raw, qname)
                if target and target != qname:
                    self.edges[qname].add(target)
                    self.reverse[target].add(qname)

    # -- queries ---------------------------------------------------------- #
    def callees(self, qname: str) -> list[str]:
        return sorted(self.edges.get(qname, ()))

    def callers(self, qname: str) -> list[str]:
        return sorted(self.reverse.get(qname, ()))

    def fan_in(self) -> dict[str, int]:
        return {q: len(self.reverse.get(q, ())) for q in self.nodes}

    def fan_out(self) -> dict[str, int]:
        return {q: len(self.edges.get(q, ())) for q in self.nodes}

    def entry_points(self, limit: int = 25) -> list[str]:
        """Functions nobody in the project calls (likely entry points)."""
        eps = [q for q in self.nodes if not self.reverse.get(q)]
        eps.sort(key=lambda q: (self.nodes[q].file, self.nodes[q].lineno))
        return eps[:limit]

    def find_paths(self, source: str, target: str, max_depth: int = 6,
                   max_paths: int = 10) -> list[list[str]]:
        """All simple call paths from *source* to *target* (BFS, bounded)."""
        if source not in self.nodes or target not in self.nodes:
            return []
        paths, queue = [], deque([[source]])
        while queue and len(paths) < max_paths:
            path = queue.popleft()
            if len(path) - 1 > max_depth:
                continue
            last = path[-1]
            if last == target:
                paths.append(path)
                continue
            for nxt in sorted(self.edges.get(last, ())):
                if nxt not in path:
                    queue.append(path + [nxt])
        return paths

    def flows_to(self, target: str, max_depth: int = 5,
                 max_paths: int = 10) -> list[list[str]]:
        """How execution can reach *target*: paths from entry points."""
        if target not in self.nodes:
            return []
        paths, queue = [], deque([[target]])
        seen_paths = 0
        while queue and seen_paths < max_paths:
            path = queue.popleft()           # path is target-first; reverse at end
            head = path[0]
            callers = self.callers(head)
            if not callers or len(path) - 1 >= max_depth:
                if len(path) > 1:            # only real flows, not the node alone
                    paths.append(list(reversed(path)))
                    seen_paths += 1
                continue
            for caller in callers:
                if caller not in path:
                    queue.append([caller] + path)
        return paths


def module_dependencies(project: Project) -> dict[str, list[str]]:
    """Map each module to the other *project* modules it imports."""
    mod_names = {m.dotted_name for m in project.modules}
    deps: dict[str, set[str]] = defaultdict(set)
    for m in project.modules:
        for imp in m.imports:
            targets = [imp.module] if imp.module else []
            if imp.is_from and imp.level:
                # `from . import foo` -> module names live in `names`
                targets.extend(imp.names)
            for target in targets:
                base = target.split(".")[0]
                for cand in mod_names:
                    if cand == target or cand.endswith("." + target) \
                            or cand.split(".")[-1] == base:
                        if cand != m.dotted_name:
                            deps[m.dotted_name].add(cand)
    return {k: sorted(v) for k, v in sorted(deps.items())}
