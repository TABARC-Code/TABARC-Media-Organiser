/* The browser is a control panel. Scans keep running on the server. */
"use strict";

const byId = id => document.getElementById(id);
const pending = new Set();

async function api(path, method = "GET", payload) {
  const options = { method, headers: { "X-Tabarc-Local": "1" } };
  if (payload !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}).`);
  return body;
}

function text(tag, value, className) {
  const el = document.createElement(tag);
  el.textContent = value;
  if (className) el.className = className;
  return el;
}

function message(value, error = false) {
  const notice = byId("notice");
  notice.hidden = false;
  notice.className = error ? "notice error" : "notice";
  notice.textContent = value;
}

function button(label, task) {
  const el = document.createElement("button");
  el.type = "button";
  el.textContent = label;
  el.addEventListener("click", async () => {
    el.disabled = true;
    try { await task(); await refresh(); }
    catch (error) { message(error.message, true); }
    finally { el.disabled = false; }
  });
  return el;
}

function selected(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`), input => input.value);
}

function renderLibraries(libraries) {
  const node = byId("libraries");
  node.replaceChildren();
  if (!libraries.length) { node.append(text("p", "No libraries added yet.", "empty")); return; }
  for (const lib of libraries) {
    const item = text("div", "", "library");
    item.append(text("strong", lib.name), text("p", lib.root, "meta"));
    item.append(text("p", `${lib.media_types.join(", ")} · ${lib.scan_profile} · ${lib.applications.join(", ") || "no consumer selected"}`, "meta"));
    const actions = text("div", "", "actions");
    actions.append(button("Scan library", async () => {
      await api(`/api/libraries/${lib.id}/scan`, "POST");
      message(`Scanning ${lib.name}. The original media will not be changed.`);
    }));
    actions.append(button("View files", async () => {
      const files = await api(`/api/libraries/${lib.id}/files?limit=30`);
      message(files.length ? files.map(f => f.relative_path).join(" · ") : "No indexed files yet. Run a scan first.");
    }));
    actions.append(button("Preview", async () => {
      const result = await api(`/api/libraries/${lib.id}/proposals?limit=500`);
      renderProposals(result.proposals);
    }));
    item.append(actions);
    node.append(item);
  }
}

function renderProposals(proposals) {
  const node = byId("proposals");
  node.replaceChildren();
  if (!proposals.length) {
    node.append(text("p", "No filename pattern suggestions in the indexed sample.", "empty"));
    return;
  }
  for (const item of proposals.slice(0, 35)) {
    const row = text("div", "", "proposal");
    row.append(text("div", item.current));
    row.append(text("span", `Suggestion: ${item.suggested_name}`));
    row.append(text("p", item.reason, "hint"));
    node.append(row);
  }
}

function renderJobs(jobs) {
  const node = byId("jobs");
  node.replaceChildren();
  if (!jobs.length) { node.append(text("p", "Nothing running.", "empty")); return; }
  for (const job of jobs.slice(0, 10)) {
    const item = text("div", "", "job");
    item.append(text("strong", `Scan #${job.id} · ${job.state.replaceAll("_", " ")}`));
    item.append(text("p", `${job.seen} files seen · ${job.errors} errors`, "meta"));
    if (job.message) item.append(text("p", job.message, "meta"));
    const actions = text("div", "", "actions");
    if (job.state === "running") {
      actions.append(button("Pause", async () => {
        await api(`/api/jobs/${job.id}/pause`, "POST");
        message("Pausing after the current file.");
      }));
    } else if (job.state === "paused") {
      actions.append(button("Resume", async () => {
        await api(`/api/jobs/${job.id}/resume`, "POST");
        message("Resuming from a fresh incremental scan.");
      }));
    }
    item.append(actions);
    node.append(item);
  }
}

async function refresh() {
  if (pending.has("refresh")) return;
  pending.add("refresh");
  try {
    const [status, libraries, jobs] = await Promise.all([
      api("/api/status"), api("/api/libraries"), api("/api/jobs")
    ]);
    byId("metric-libraries").textContent = status.libraries.toLocaleString("en-GB");
    byId("metric-files").textContent = status.files.toLocaleString("en-GB");
    byId("metric-worker").textContent = jobs.some(j => j.state === "running") ? "Scanning" : "Idle";
    renderLibraries(libraries);
    renderJobs(jobs);
  } catch (error) { message(error.message, true); }
  finally { pending.delete("refresh"); }
}

byId("library-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    const media_types = selected("media");
    if (!media_types.length) throw new Error("Choose at least one media type.");
    const payload = {
      name: byId("library-name").value.trim(),
      root: byId("library-root").value.trim(),
      media_types,
      applications: selected("app"),
      scan_profile: byId("scan-profile").value
    };
    const library = await api("/api/libraries", "POST", payload);
    message(`Added ${library.name}. Select Scan library when you're ready.`);
    form.reset();
    await refresh();
  } catch (error) { message(error.message, true); }
  finally { submit.disabled = false; }
});

refresh();
setInterval(refresh, 2500);
