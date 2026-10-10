/* CodeAtlas project page logic */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

/* tabs */
document.querySelectorAll(".tab").forEach((t) => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach((x) => x.classList.add("hidden"));
    t.classList.add("active");
    $("tab-" + t.dataset.tab).classList.remove("hidden");
  });
});

/* overview */
fetch(`/api/${PID}/overview`).then((r) => r.json()).then((d) => {
  $("ov-summary").innerHTML = "<p>" + esc(d.summary).replace(/\n/g, "<br>") + "</p>";
  $("ov-stats").innerHTML = ["modules|Modules", "functions|Functions", "classes|Classes", "loc|Lines"]
    .map(([k, l]) => `<div class="stat"><b>${d.stats[k]}</b><span class="muted">${l}</span></div>`).join("");
  $("ov-risk").innerHTML = d.riskiest.map((f) =>
    `<tr><td><code>${esc(f.qualified_name)}</code></td><td class="muted">${esc(f.file)}:${f.lineno}</td>` +
    `<td><span class="pill ${f.risk_level}">${f.risk_level}</span></td><td>${f.risk_score}</td><td>${f.complexity}</td></tr>`).join("");
  $("ov-mods").innerHTML = d.modules.map((m) =>
    `<tr><td><code>${esc(m.dotted_name)}</code></td><td class="muted">${esc(m.path)}</td>` +
    `<td>${m.functions}</td><td>${m.classes}</td><td>${m.loc}</td></tr>`).join("");
});

/* function search + detail */
let debounce;
$("q").addEventListener("input", (e) => {
  clearTimeout(debounce);
  debounce = setTimeout(() => search(e.target.value), 220);
});
async function search(q) {
  if (!q.trim()) { $("results").innerHTML = '<p class="muted">Type to search.</p>'; return; }
  const d = await (await fetch(`/api/${PID}/search?q=${encodeURIComponent(q)}`)).json();
  $("results").innerHTML = d.results.length
    ? d.results.map((f) =>
        `<div class="fitem" data-name="${esc(f.qualified_name)}"><div class="qn">${esc(f.qualified_name)}</div>` +
        `<div class="loc">${esc(f.file)}:${f.lineno} · <span class="pill ${f.risk_level}">${f.risk_level}</span></div></div>`).join("")
    : '<p class="muted">No matches.</p>';
  document.querySelectorAll(".fitem").forEach((el) =>
    el.addEventListener("click", () => showFunction(el.dataset.name)));
}
async function showFunction(name) {
  const f = await (await fetch(`/api/${PID}/function?name=${encodeURIComponent(name)}`)).json();
  if (f.error) { $("detail").innerHTML = `<p>${esc(f.error)}</p>`; return; }
  const link = (c) => `<code>${esc(c.name)}</code> <span class="muted">${esc(c.file)}:${c.lineno}</span>`;
  $("detail").innerHTML =
    `<h3><code>${esc(f.qualified_name)}</code> <span class="pill ${f.risk_level}">${f.risk_level} ${f.risk_score}</span></h3>` +
    `<p class="muted">${esc(f.file)}:${f.lineno}–${f.end_lineno} · complexity ${f.complexity} · ${f.loc} lines</p>` +
    `<p><strong>Signature:</strong> <code>${esc(f.name)}(${esc(f.args.join(", "))})</code></p>` +
    `<p>${esc(f.summary)}</p>` +
    (f.docstring ? `<p><strong>Docstring:</strong> ${esc(f.docstring.split("\n")[0])}</p>` : "") +
    `<p><strong>Calls:</strong> ${f.callees.length ? f.callees.map(link).join(", ") : "(none)"}</p>` +
    `<p><strong>Called by:</strong> ${f.callers.length ? f.callers.map(link).join(", ") : "(no in-project callers)"}</p>` +
    (f.suggestions.length ? `<p><strong>Suggestions:</strong></p><ul>${f.suggestions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : "") +
    (f.flows.length ? `<p><strong>Flows reaching it:</strong></p><ul>${f.flows.map((p) => `<li>${p.map((q) => `<code>${esc(q.split(".").pop())}</code>`).join(" → ")}</li>`).join("")}</ul>` : "") +
    `<pre>${esc(f.source)}</pre>`;
}

/* tracer */
$("t-go").addEventListener("click", async () => {
  const a = $("t-from").value.trim(), b = $("t-to").value.trim();
  if (!a || !b) return;
  $("t-out").innerHTML = '<p class="muted">Tracing…</p>';
  const d = await (await fetch(`/api/${PID}/trace?from=${encodeURIComponent(a)}&to=${encodeURIComponent(b)}`)).json();
  if (d.error) { $("t-out").innerHTML = `<p>${esc(d.error)}</p>`; return; }
  $("t-out").innerHTML = d.paths.length
    ? `<p>Paths from <code>${esc(d.from)}</code> to <code>${esc(d.to)}</code>:</p><ul>` +
      d.paths.map((p) => `<li>${p.map((q) => `<code>${esc(q)}</code>`).join(" → ")}</li>`).join("") + "</ul>"
    : `<p class="muted">No call path found within 6 hops.</p>`;
});

/* chat */
function addMsg(who, html) {
  const div = document.createElement("div");
  div.className = "msg " + who;
  div.innerHTML = `<span class="bubble">${html}</span>`;
  $("chatlog").appendChild(div);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}
function mdLite(t) {
  return esc(t)
    .replace(/^### (.*)$/gm, "<h3>$1</h3>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br>");
}
async function askChat() {
  const q = $("chatq").value.trim();
  if (!q) return;
  $("chatq").value = "";
  addMsg("you", esc(q));
  addMsg("bot", '<span class="muted">Thinking…</span>');
  const d = await (await fetch(`/api/${PID}/chat`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ question: q }),
  })).json();
  $("chatlog").lastChild.querySelector(".bubble").innerHTML = mdLite(d.answer || d.error);
}
$("chatgo").addEventListener("click", askChat);
$("chatq").addEventListener("keydown", (e) => { if (e.key === "Enter") askChat(); });
addMsg("bot", mdLite("Hi! Ask me about this codebase — e.g. `explain load_data`, `who calls save_report`, `trace main to export_csv`, or `riskiest functions`."));
