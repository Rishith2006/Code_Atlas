"""CodeAtlas web app: upload a ZIP, explore, chat, download reports."""
from __future__ import annotations

import io
import json
import os
import shutil
import uuid
import zipfile

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for

from .analysis import analyze_project
from .chatbot import ProjectChat
from .graph import CallGraph
from .llm import Summarizer
from .parser import parse_project
from .reports import generate_report

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Vercel serverless instances have a read-only filesystem except /tmp,
# so uploads go there when running on Vercel (or when overridden).
if os.environ.get("CODEATLAS_UPLOAD_DIR"):
    UPLOAD_DIR = os.environ["CODEATLAS_UPLOAD_DIR"]
elif os.environ.get("VERCEL"):
    UPLOAD_DIR = "/tmp/codeatlas_uploads"
else:
    UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB zips

# project_id -> bundle dict
PROJECTS: dict[str, dict] = {}


def _load_bundle(pid: str):
    b = PROJECTS.get(pid)
    if b:
        return b
    meta_path = os.path.join(UPLOAD_DIR, pid, "meta.json")
    if not os.path.exists(meta_path):
        return None
    with open(meta_path) as fh:
        meta = json.load(fh)
    root = os.path.join(UPLOAD_DIR, pid, "src")
    project = parse_project(root, meta["name"])
    graph = CallGraph(project)
    analyze_project(project, graph.fan_in(), graph.fan_out())
    b = {"name": meta["name"], "root": root, "project": project, "graph": graph,
         "chat": ProjectChat(project, graph)}
    PROJECTS[pid] = b
    return b


def _register_project(name: str, src_dir: str) -> str:
    pid = uuid.uuid4().hex[:12]
    dest = os.path.join(UPLOAD_DIR, pid, "src")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src_dir, dest)
    with open(os.path.join(UPLOAD_DIR, pid, "meta.json"), "w") as fh:
        json.dump({"name": name}, fh)
    PROJECTS.pop(pid, None)
    _load_bundle(pid)
    return pid


def _safe_extract(zf: zipfile.ZipFile, dest: str):
    """Extract guarding against zip-slip."""
    for member in zf.infolist():
        target = os.path.abspath(os.path.join(dest, member.filename))
        if not target.startswith(os.path.abspath(dest) + os.sep):
            raise ValueError(f"Unsafe path in zip: {member.filename}")
    zf.extractall(dest)


def _project_root(extracted: str) -> str:
    """If the zip contains a single top-level folder, use it as root."""
    entries = [e for e in os.listdir(extracted) if not e.startswith(".")]
    if len(entries) == 1 and os.path.isdir(os.path.join(extracted, entries[0])):
        return os.path.join(extracted, entries[0])
    return extracted


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

@app.route("/")
def index():
    items = []
    for pid in sorted(os.listdir(UPLOAD_DIR)):
        meta = os.path.join(UPLOAD_DIR, pid, "meta.json")
        if os.path.exists(meta):
            with open(meta) as fh:
                items.append({"id": pid, "name": json.load(fh)["name"]})
    return render_template("index.html", projects=items)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file or not file.filename.lower().endswith(".zip"):
        return "Please upload a .zip file.", 400
    pid = uuid.uuid4().hex[:12]
    tmp = os.path.join(UPLOAD_DIR, pid, "raw")
    os.makedirs(tmp, exist_ok=True)
    zpath = os.path.join(tmp, "upload.zip")
    file.save(zpath)
    try:
        with zipfile.ZipFile(zpath) as zf:
            _safe_extract(zf, tmp)
    except Exception as exc:
        shutil.rmtree(os.path.join(UPLOAD_DIR, pid), ignore_errors=True)
        return f"Could not read zip: {exc}", 400
    name = os.path.splitext(file.filename)[0]
    root = _project_root(tmp)
    dest = os.path.join(UPLOAD_DIR, pid, "src")
    shutil.copytree(root, dest)
    shutil.rmtree(tmp, ignore_errors=True)
    with open(os.path.join(UPLOAD_DIR, pid, "meta.json"), "w") as fh:
        json.dump({"name": name}, fh)
    _load_bundle(pid)
    return redirect(url_for("project_page", pid=pid))


@app.route("/sample")
def load_sample():
    sample = os.path.join(BASE_DIR, "sample_project")
    pid = _register_project("sample_project", sample)
    return redirect(url_for("project_page", pid=pid))


@app.route("/project/<pid>")
def project_page(pid):
    b = _load_bundle(pid)
    if not b:
        return "Project not found.", 404
    return render_template("project.html", pid=pid, name=b["name"])


# --------------------------------------------------------------------------- #
# JSON API
# --------------------------------------------------------------------------- #

def _func_json(f):
    return {
        "name": f.name, "qualified_name": f.qualified_name,
        "file": f.file, "lineno": f.lineno, "end_lineno": f.end_lineno,
        "args": f.args, "docstring": f.docstring, "source": f.source,
        "complexity": f.complexity, "loc": f.loc,
        "risk_score": f.risk_score, "risk_level": f.risk_level,
        "suggestions": f.suggestions,
        "is_method": f.is_method, "class_name": f.class_name,
        "decorators": f.decorators,
    }


@app.route("/api/<pid>/overview")
def api_overview(pid):
    b = _load_bundle(pid)
    if not b:
        return jsonify({"error": "not found"}), 404
    p, g = b["project"], b["graph"]
    summary = Summarizer().project_overview(p)
    funcs = sorted(p.all_functions(), key=lambda f: -f.risk_score)
    return jsonify({
        "name": p.name,
        "summary": summary,
        "stats": {
            "modules": len(p.modules),
            "functions": len(funcs),
            "classes": sum(len(m.classes) for m in p.modules),
            "loc": sum(m.loc for m in p.modules),
        },
        "modules": [{"path": m.path, "dotted_name": m.dotted_name,
                     "functions": len(m.functions), "classes": len(m.classes),
                     "loc": m.loc} for m in p.modules],
        "riskiest": [_func_json(f) for f in funcs[:10]],
        "entry_points": g.entry_points(15),
    })


@app.route("/api/<pid>/search")
def api_search(pid):
    b = _load_bundle(pid)
    if not b:
        return jsonify({"error": "not found"}), 404
    q = request.args.get("q", "")
    return jsonify({"results": [_func_json(f)
                                for f in b["project"].search_functions(q)]})


@app.route("/api/<pid>/function")
def api_function(pid):
    b = _load_bundle(pid)
    if not b:
        return jsonify({"error": "not found"}), 404
    name = request.args.get("name", "")
    f = b["project"].find_function(name)
    if not f:
        return jsonify({"error": f"no function named '{name}'"}), 404
    g = b["graph"]
    data = _func_json(f)
    data["summary"] = Summarizer().summarize_function(f)
    data["callers"] = [{"name": c, "file": g.nodes[c].file,
                        "lineno": g.nodes[c].lineno} for c in g.callers(f.qualified_name)]
    data["callees"] = [{"name": c, "file": g.nodes[c].file,
                        "lineno": g.nodes[c].lineno} for c in g.callees(f.qualified_name)]
    data["flows"] = g.flows_to(f.qualified_name)
    return jsonify(data)


@app.route("/api/<pid>/trace")
def api_trace(pid):
    b = _load_bundle(pid)
    if not b:
        return jsonify({"error": "not found"}), 404
    src = b["project"].find_function(request.args.get("from", ""))
    dst = b["project"].find_function(request.args.get("to", ""))
    if not src or not dst:
        return jsonify({"error": "could not resolve one of the functions"}), 400
    paths = b["graph"].find_paths(src.qualified_name, dst.qualified_name)
    return jsonify({"from": src.qualified_name, "to": dst.qualified_name,
                    "paths": paths})


@app.route("/api/<pid>/chat", methods=["POST"])
def api_chat(pid):
    b = _load_bundle(pid)
    if not b:
        return jsonify({"error": "not found"}), 404
    question = (request.get_json(silent=True) or {}).get("question", "")
    if not question.strip():
        return jsonify({"error": "empty question"}), 400
    return jsonify({"answer": b["chat"].ask(question)})


@app.route("/api/<pid>/report")
def api_report(pid):
    b = _load_bundle(pid)
    if not b:
        return jsonify({"error": "not found"}), 404
    md = generate_report(b["project"], b["graph"])
    buf = io.BytesIO(md.encode("utf-8"))
    return send_file(buf, as_attachment=True,
                     download_name=f"{b['name']}-codeatlas-report.md",
                     mimetype="text/markdown")


def main():
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)


if __name__ == "__main__":
    main()
