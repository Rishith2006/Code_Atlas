"""LLM-backed summarization with a graceful offline fallback.

Configure with environment variables:
    OPENAI_API_KEY  (or CODEATLAS_API_KEY)  - enables LLM summaries
    OPENAI_BASE_URL - OpenAI-compatible endpoint (default https://api.openai.com/v1)
    CODEATLAS_MODEL - model name (default gpt-4o-mini)

Without a key, CodeAtlas falls back to a heuristic summarizer built from
docstrings, signatures and call sites - so the whole tool works offline.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .parser import FunctionInfo, ModuleInfo, Project


class Summarizer:
    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("CODEATLAS_API_KEY")
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.environ.get("CODEATLAS_MODEL", "gpt-4o-mini")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    # -- public API ------------------------------------------------------- #
    def summarize_function(self, func: FunctionInfo) -> str:
        if self.available:
            try:
                return self._chat(
                    "You are a senior engineer writing terse code documentation.",
                    f"Summarize this Python function in 2-3 sentences: what it does, "
                    f"key inputs/outputs, and anything risky.\n\n"
                    f"Function: {func.qualified_name}\n"
                    f"Signature: {func.name}({', '.join(func.args)})\n"
                    f"Docstring: {func.docstring or '(none)'}\n"
                    f"Calls: {', '.join(func.calls[:15]) or '(none)'}\n"
                    f"Source:\n{func.source[:3000]}")
            except Exception:
                pass
        return self._heuristic_function_summary(func)

    def summarize_module(self, module: ModuleInfo) -> str:
        names = [f.name for f in module.functions if not f.is_method][:12]
        classes = [c.name for c in module.classes]
        parts = [f"`{module.dotted_name}` ({module.loc} lines)"]
        if classes:
            parts.append("classes: " + ", ".join(f"`{c}`" for c in classes))
        if names:
            parts.append("functions: " + ", ".join(f"`{n}`" for n in names))
        if module.docstring:
            parts.append(module.docstring.strip().split("\n")[0])
        return " - ".join(parts) + "."

    def project_overview(self, project: Project) -> str:
        n_func = len(project.all_functions())
        n_cls = sum(len(m.classes) for m in project.modules)
        if self.available:
            try:
                mods = "\n".join(
                    f"- {m.dotted_name}: {(m.docstring or '').split(chr(10))[0][:120]}"
                    for m in project.modules[:20])
                return self._chat(
                    "You are a software architect.",
                    f"Write a 4-6 sentence overview of this Python project: its apparent "
                    f"purpose, architecture and major components.\n\n"
                    f"Project: {project.name} - {len(project.modules)} modules, "
                    f"{n_func} functions, {n_cls} classes.\nModules:\n{mods}")
            except Exception:
                pass
        lines = [f"**{project.name}** - {len(project.modules)} modules, "
                 f"{n_func} functions, {n_cls} classes."]
        for m in project.modules[:15]:
            first = (m.docstring or "").strip().split("\n")[0]
            lines.append(f"- `{m.dotted_name}`: {first[:100]}" if first
                         else f"- `{m.dotted_name}`")
        return "\n".join(lines)

    # -- internals --------------------------------------------------------- #
    def _heuristic_function_summary(self, func: FunctionInfo) -> str:
        if func.docstring:
            first = func.docstring.strip().split("\n")[0].strip()
            base = first
        else:
            base = (f"`{func.name}` takes ({', '.join(func.args) or 'no args'}) "
                    f"and spans lines {func.lineno}-{func.end_lineno} "
                    f"in `{func.file}`.")
        calls = [c for c in func.calls if not c.startswith("<")][:8]
        if calls:
            base += " It calls: " + ", ".join(f"`{c}`" for c in calls) + "."
        if func.complexity >= 10:
            base += f" Note: high complexity ({func.complexity}) - review carefully."
        return base

    def _chat(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": 400,
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=payload,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
