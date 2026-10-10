"""Rule-based project Q&A. Every answer cites real file:line locations.

If an LLM key is configured, answers are polished by the model using only
retrieved project context; otherwise the structured rule-based answer is
returned directly. Either way, facts come from the parsed codebase.
"""
from __future__ import annotations

import re

from .analysis import riskiest_functions
from .graph import CallGraph
from .llm import Summarizer
from .parser import Project


def _ref(func) -> str:
    return f"`{func.file}:{func.lineno}`"


class ProjectChat:
    def __init__(self, project: Project, graph: CallGraph,
                 summarizer: Summarizer | None = None):
        self.project = project
        self.graph = graph
        self.summarizer = summarizer or Summarizer()

    # -- main entry -------------------------------------------------------- #
    def ask(self, question: str) -> str:
        q = question.strip()
        ql = q.lower()

        m = re.search(r"(?:trace|path|flow|how does|how can)\s+(?:[`'\"]?)(\w[\w.]*)(?:[`'\"]?)\s+(?:to|reach|call)\s+(?:[`'\"]?)(\w[\w.]*)(?:[`'\"]?)", ql)
        if m:
            return self._trace(m.group(1), m.group(2))
        if re.search(r"\b(riskiest|most risky|risky functions|risk)\b", ql):
            return self._riskiest()
        m = re.search(r"who calls\s+(?:[`'\"]?)(\w[\w.]*)(?:[`'\"]?)", ql)
        if m:
            return self._callers(m.group(1))
        m = re.search(r"what does\s+(?:[`'\"]?)(\w[\w.]*)(?:[`'\"]?)\s+call", ql)
        if m:
            return self._callees(m.group(1))
        m = re.search(r"(?:what does|explain|describe|show me)\s+(?:[`'\"]?)(\w[\w.]*)(?:[`'\"]?)", ql)
        if m:
            return self._explain(m.group(1))
        if re.search(r"\b(overview|summar|about this project|what is this)\b", ql):
            return self._overview()
        if re.search(r"\blist\b.*\bfunctions?\b", ql) or re.search(r"\bfunctions?\b.*\blist\b", ql):
            return self._list_functions()
        if re.search(r"\b(entry|main|starting? points?)\b", ql):
            return self._entries()

        # fallback: keyword search, then LLM polish if available
        hits = self.project.search_functions(q, limit=5)
        if hits:
            lines = [f"Found {len(hits)} match(es):"]
            for f in hits:
                lines.append(f"- `{f.qualified_name}` {_ref(f)} - "
                             f"{(f.docstring.split(chr(10))[0] if f.docstring else 'no docstring')[:80]}")
            answer = "\n".join(lines)
        else:
            answer = ("I couldn't find anything matching that. Try asking e.g. "
                      "`explain <function>`, `who calls <function>`, "
                      "`trace <a> to <b>`, `riskiest functions`, or `overview`.")
        return self._maybe_polish(q, answer)

    # -- intent handlers ---------------------------------------------------- #
    def _explain(self, name: str) -> str:
        f = self.project.find_function(name)
        if not f:
            return f"No function named `{name}` found in this project."
        summary = self.summarizer.summarize_function(f)
        callers = self.graph.callers(f.qualified_name)
        callees = self.graph.callees(f.qualified_name)
        lines = [
            f"### `{f.qualified_name}` {_ref(f)}",
            "",
            summary,
            "",
            f"- **Signature:** `{f.name}({', '.join(f.args)})`",
            f"- **Complexity:** {f.complexity} | **Risk:** {f.risk_level} ({f.risk_score}) | **Lines:** {f.loc}",
            f"- **Calls:** {', '.join(f'`{c}`' for c in callees) or '(none)'}",
            f"- **Called by:** {', '.join(f'`{c}`' for c in callers) or '(no in-project callers)'}",
        ]
        if f.suggestions:
            lines.append("- **Suggestions:**")
            lines += [f"  - {s}" for s in f.suggestions]
        return "\n".join(lines)

    def _callers(self, name: str) -> str:
        f = self.project.find_function(name)
        if not f:
            return f"No function named `{name}` found."
        callers = self.graph.callers(f.qualified_name)
        if not callers:
            return (f"`{f.qualified_name}` {_ref(f)} has no callers inside this "
                    f"project - it may be an entry point or dead code.")
        lines = [f"Functions that call `{f.qualified_name}` {_ref(f)}:"]
        for c in callers:
            cf = self.graph.nodes[c]
            lines.append(f"- `{c}` {_ref(cf)}")
        return "\n".join(lines)

    def _callees(self, name: str) -> str:
        f = self.project.find_function(name)
        if not f:
            return f"No function named `{name}` found."
        callees = self.graph.callees(f.qualified_name)
        if not callees:
            return f"`{f.qualified_name}` {_ref(f)} calls no other project functions."
        lines = [f"`{f.qualified_name}` {_ref(f)} calls:"]
        for c in callees:
            cf = self.graph.nodes[c]
            lines.append(f"- `{c}` {_ref(cf)}")
        return "\n".join(lines)

    def _trace(self, src: str, dst: str) -> str:
        sf, df = self.project.find_function(src), self.project.find_function(dst)
        if not sf or not df:
            missing = src if not sf else dst
            return f"Couldn't resolve `{missing}` to a project function."
        paths = self.graph.find_paths(sf.qualified_name, df.qualified_name)
        if not paths:
            return (f"No call path found from `{sf.qualified_name}` to "
                    f"`{df.qualified_name}` (within 6 hops).")
        lines = [f"Call path(s) from `{sf.qualified_name}` to `{df.qualified_name}`:"]
        for p in paths:
            segs = []
            for q in p:
                fn = self.graph.nodes[q]
                segs.append(f"`{q.split('.')[-1]}`({_ref(fn)})")
            lines.append(f"{len(p)-1} hop(s): " + " -> ".join(segs))
        return "\n".join(lines)

    def _flows_to(self, name: str) -> str:
        f = self.project.find_function(name)
        if not f:
            return f"No function named `{name}` found."
        flows = self.graph.flows_to(f.qualified_name)
        if not flows:
            return f"No in-project flows reach `{f.qualified_name}` - likely an entry point."
        lines = [f"How execution reaches `{f.qualified_name}` {_ref(f)}:"]
        for p in flows:
            lines.append(" <- ".join(f"`{q.split('.')[-1]}`" for q in p))
        return "\n".join(lines)

    def _riskiest(self, n: int = 8) -> str:
        top = riskiest_functions(self.project, n)
        lines = [f"Top {len(top)} riskiest functions (complexity + dependencies + docs):"]
        for f in top:
            lines.append(f"- `{f.qualified_name}` {_ref(f)} - "
                         f"**{f.risk_level}** ({f.risk_score}), complexity {f.complexity}, "
                         f"{f.loc} lines")
        return "\n".join(lines)

    def _overview(self) -> str:
        return self.summarizer.project_overview(self.project)

    def _list_functions(self) -> str:
        funcs = sorted(self.project.all_functions(), key=lambda f: f.qualified_name)
        lines = [f"{len(funcs)} functions:"]
        for f in funcs[:40]:
            lines.append(f"- `{f.qualified_name}` {_ref(f)}")
        if len(funcs) > 40:
            lines.append(f"... and {len(funcs) - 40} more. Search to narrow down.")
        return "\n".join(lines)

    def _entries(self) -> str:
        eps = self.graph.entry_points()
        lines = ["Likely entry points (no in-project callers):"]
        for q in eps:
            f = self.graph.nodes[q]
            lines.append(f"- `{q}` {_ref(f)}")
        return "\n".join(lines)

    # -- LLM polish --------------------------------------------------------- #
    def _maybe_polish(self, question: str, draft: str) -> str:
        if not self.summarizer.available:
            return draft
        try:
            return self.summarizer._chat(
                "You are CodeAtlas, a codebase assistant. Rewrite the draft answer "
                "clearly in markdown. Do NOT invent file names or line numbers; keep "
                "every `file:line` reference from the draft exactly.",
                f"Question: {question}\n\nDraft answer:\n{draft}")
        except Exception:
            return draft
