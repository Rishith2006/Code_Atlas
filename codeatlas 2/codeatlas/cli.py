"""CodeAtlas CLI: analyze a project, print reports, chat, or serve the web UI."""
from __future__ import annotations

import argparse
import os
import sys

from .analysis import analyze_project, riskiest_functions
from .chatbot import ProjectChat
from .graph import CallGraph, module_dependencies
from .llm import Summarizer
from .parser import parse_project
from .reports import generate_report


def _load(path: str, name: str | None = None):
    project = parse_project(path, name)
    graph = CallGraph(project)
    analyze_project(project, graph.fan_in(), graph.fan_out())
    return project, graph


def cmd_analyze(args):
    project, graph = _load(args.path, args.name)
    print(f"Project: {project.name}")
    print(f"Modules: {len(project.modules)}  "
          f"Functions: {len(project.all_functions())}  "
          f"Classes: {sum(len(m.classes) for m in project.modules)}")
    print("\nRiskiest functions:")
    for f in riskiest_functions(project, args.top):
        print(f"  [{f.risk_level:8s}] {f.risk_score:5.1f}  "
              f"{f.qualified_name} ({f.file}:{f.lineno})")
    if args.deps:
        print("\nModule dependencies:")
        for mod, ds in module_dependencies(project).items():
            print(f"  {mod} -> {', '.join(ds)}")


def cmd_report(args):
    project, graph = _load(args.path, args.name)
    md = generate_report(project, graph)
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(md)
        print(f"Report written to {args.output}")
    else:
        print(md)


def cmd_chat(args):
    project, graph = _load(args.path, args.name)
    chat = ProjectChat(project, graph)
    print(f"CodeAtlas chat - {project.name}. Ask about functions, risks, call flows.")
    print("Type 'quit' to exit.\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"quit", "exit"}:
            break
        if q:
            print("\n" + chat.ask(q) + "\n")


def cmd_serve(args):
    from .app import app
    print(f"CodeAtlas web UI on http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=False)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="codeatlas",
                                 description="AI Codebase Investigator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("analyze", help="parse + risk analysis summary")
    p.add_argument("path", help="project directory (or extracted zip)")
    p.add_argument("--name", default=None)
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--deps", action="store_true", help="show module dependencies")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("report", help="generate markdown report")
    p.add_argument("path")
    p.add_argument("--name", default=None)
    p.add_argument("-o", "--output", default=None)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("chat", help="interactive Q&A over the codebase")
    p.add_argument("path")
    p.add_argument("--name", default=None)
    p.set_defaults(fn=cmd_chat)

    p = sub.add_parser("serve", help="start the web UI")
    p.add_argument("--port", type=int, default=5000)
    p.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
