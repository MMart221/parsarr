/* parsarr frontend — vanilla JS, no build step */

"use strict";

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let msg = `${resp.status} ${resp.statusText}`;
    try { msg = (await resp.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json() : resp.text();
}

function showToast(msg, type = "info") {
  const el = document.createElement("div");
  el.className = `alert alert-${type}`;
  el.style.cssText = "position:fixed;top:1rem;right:1rem;z-index:999;max-width:360px;";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ---------------------------------------------------------------------------
// Queue page — auto-refresh every 10 s + per-row delete
// ---------------------------------------------------------------------------

function initQueue() {
  const table = document.getElementById("jobs-table");
  if (!table) return;

  async function refresh() {
    try {
      const jobs = await api("GET", "/api/jobs");
      const tbody = table.querySelector("tbody");
      if (!tbody) return;
      tbody.innerHTML = jobs.map(renderJobRow).join("");
      bindQueueDeleteButtons(tbody);
    } catch (e) {
      console.warn("Queue refresh failed:", e);
    }
  }

  // Bind delete buttons on initial server-rendered rows
  bindQueueDeleteButtons(table.querySelector("tbody"));

  setInterval(refresh, 10000);
}

function bindQueueDeleteButtons(container) {
  if (!container) return;
  container.querySelectorAll(".btn-delete-job").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const jobId = btn.dataset.id;
      if (!confirm(`Delete job #${jobId}? The torrent will be removed from qBittorrent (downloaded files kept).`)) return;
      try {
        await api("DELETE", `/api/jobs/${jobId}`);
        const row = btn.closest("tr");
        if (row) row.remove();
        showToast(`Job #${jobId} deleted`, "success");
      } catch (e) {
        showToast("Delete failed: " + e.message, "danger");
      }
    });
  });
}

function renderJobRow(job) {
  const holdBadge = job.hold ? `<span class="badge badge-hold">hold</span>` : "";
  const dt = job.updated_at ? job.updated_at.slice(0, 16).replace("T", " ") : "";
  return `<tr>
    <td><a class="table-link" href="/jobs/${job.id}">#${job.id}</a></td>
    <td><a class="table-link" href="/jobs/${job.id}">${escHtml(job.title)}</a></td>
    <td><span class="badge badge-${job.state}">${job.state}</span> ${holdBadge}</td>
    <td class="text-muted text-small mono">${job.hash ? job.hash.slice(0, 8) : ""}</td>
    <td class="text-muted text-small">${dt}</td>
    <td><button class="btn btn-ghost btn-delete-job text-small" data-id="${job.id}" style="padding:0.25rem 0.5rem;color:var(--danger);">✕</button></td>
  </tr>`;
}

// ---------------------------------------------------------------------------
// Job detail page
// ---------------------------------------------------------------------------

function initJobDetail() {
  const jobId = document.getElementById("job-id")?.dataset.id;
  if (!jobId) return;

  // Hold toggle
  const holdToggle = document.getElementById("hold-toggle");
  const holdBadge  = document.getElementById("hold-badge");
  const holdHint   = document.getElementById("hold-hint");
  const approveBtn = document.getElementById("approve-btn");

  function updateHoldUI(held) {
    if (holdBadge) {
      holdBadge.style.display = held ? "" : "none";
    }
    if (holdHint) {
      if (held) {
        holdHint.className = "text-small mt-1 hold-on";
        holdHint.textContent = "Hold is on. The job is paused. Review the mapping below, then click Approve & Place to continue.";
      } else {
        holdHint.className = "text-small mt-1 text-muted";
        holdHint.textContent = "Hold is off. Parsarr will place this release automatically when it is ready. Enable Hold to pause and review before placement.";
      }
    }
    if (approveBtn) {
      const stateBadge = document.getElementById("state-badge");
      const state = stateBadge ? stateBadge.textContent.trim() : "";
      approveBtn.disabled = !held || !["ready_to_process", "auto_mapped", "awaiting_manual_mapping"].includes(state);
    }
  }

  if (holdToggle) {
    holdToggle.addEventListener("change", async () => {
      const held = holdToggle.checked;
      try {
        await api("PATCH", `/api/jobs/${jobId}/hold`, { hold: held });
        showToast(held ? "Hold enabled" : "Hold disabled", "info");
        updateHoldUI(held);
      } catch (e) {
        showToast("Failed to update hold: " + e.message, "danger");
        holdToggle.checked = !held;
      }
    });
  }

  // Approve button
  if (approveBtn) {
    approveBtn.addEventListener("click", async () => {
      approveBtn.disabled = true;
      try {
        await api("POST", `/api/jobs/${jobId}/approve`);
        showToast("Job approved — placement starting", "success");
        setTimeout(() => location.reload(), 1500);
      } catch (e) {
        showToast("Approve failed: " + e.message, "danger");
        approveBtn.disabled = false;
      }
    });
  }

  // Delete buttons
  document.getElementById("delete-btn")?.addEventListener("click", async () => {
    if (!confirm("Delete this job? The torrent will be removed from qBittorrent (downloaded files kept on disk).")) return;
    try {
      await api("DELETE", `/api/jobs/${jobId}`);
      showToast("Job deleted", "success");
      setTimeout(() => { window.location.href = "/"; }, 800);
    } catch (e) {
      showToast("Delete failed: " + e.message, "danger");
    }
  });

  document.getElementById("delete-files-btn")?.addEventListener("click", async () => {
    if (!confirm("Delete this job AND its downloaded files? This cannot be undone.")) return;
    try {
      await api("DELETE", `/api/jobs/${jobId}?delete_files=true`);
      showToast("Job and files deleted", "success");
      setTimeout(() => { window.location.href = "/"; }, 800);
    } catch (e) {
      showToast("Delete failed: " + e.message, "danger");
    }
  });

  // Mapping form
  const mappingForm = document.getElementById("mapping-form");
  if (mappingForm) {
    const seriesSearch = document.getElementById("series-search");
    const seriesList = document.getElementById("series-list");
    if (seriesSearch && seriesList) {
      let debounce;
      seriesSearch.addEventListener("input", () => {
        clearTimeout(debounce);
        debounce = setTimeout(async () => {
          const q = seriesSearch.value.trim();
          if (q.length < 2) { seriesList.innerHTML = ""; return; }
          try {
            const results = await api("GET", `/api/series?q=${encodeURIComponent(q)}`);
            seriesList.innerHTML = results.slice(0, 8).map(s =>
              `<option data-id="${s.id}" data-path="${escHtml(s.path || "")}" value="${escHtml(s.title)} (${s.year || "?"})"></option>`
            ).join("");
          } catch (_) {}
        }, 300);
      });
    }

    mappingForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(mappingForm);
      const selectedOption = seriesList
        ? Array.from(seriesList.options).find(o => o.value === fd.get("series_title"))
        : null;

      const payload = {
        series_title: fd.get("series_title") || undefined,
        series_id: selectedOption ? parseInt(selectedOption.dataset.id) : undefined,
        target_path: fd.get("target_path") || undefined,
        seasons: fd.get("seasons")
          ? fd.get("seasons").split(",").map(s => parseInt(s.trim())).filter(Boolean)
          : undefined,
      };

      try {
        await api("PATCH", `/api/jobs/${jobId}/mapping`, payload);
        showToast("Mapping updated", "success");
        setTimeout(() => location.reload(), 1000);
      } catch (e) {
        showToast("Failed to update mapping: " + e.message, "danger");
      }
    });
  }

  // Auto-refresh state badge + hold state every 8 s
  const stateBadge = document.getElementById("state-badge");
  if (stateBadge) {
    setInterval(async () => {
      try {
        const job = await api("GET", `/api/jobs/${jobId}`);
        stateBadge.className = `badge badge-${job.state}`;
        stateBadge.textContent = job.state;
        if (holdToggle && holdToggle.checked !== job.hold) {
          holdToggle.checked = job.hold;
          updateHoldUI(job.hold);
        }
        if (approveBtn) {
          approveBtn.disabled = !job.hold || !["ready_to_process", "auto_mapped", "awaiting_manual_mapping"].includes(job.state);
        }
      } catch (_) {}
    }, 8000);
  }
}

// ---------------------------------------------------------------------------
// Add page
// ---------------------------------------------------------------------------

function initAdd() {
  const form = document.getElementById("add-form");
  if (!form) return;

  const seriesDatalist = document.getElementById("series-options");
  if (seriesDatalist) {
    api("GET", "/api/series").then(results => {
      seriesDatalist.innerHTML = results.map(s =>
        `<option data-id="${s.id}" value="${escHtml(s.title)} (${s.year || "?"})"></option>`
      ).join("");
    }).catch(() => {});
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;

    const seriesTitle = fd.get("series_title") || "";
    const matchedOption = seriesDatalist
      ? Array.from(seriesDatalist.options).find(o => o.value === seriesTitle)
      : null;

    const payload = {
      magnet: fd.get("magnet"),
      title: fd.get("title") || undefined,
      series_id: matchedOption ? parseInt(matchedOption.dataset.id) : undefined,
      season: fd.get("season") ? parseInt(fd.get("season")) : undefined,
      media_type: fd.get("media_type") || "tv",
      hold: fd.get("hold") === "on",
    };

    try {
      const result = await api("POST", "/api/add", payload);
      showToast(`Job #${result.job_id} created`, "success");
      setTimeout(() => { window.location.href = `/jobs/${result.job_id}`; }, 800);
    } catch (e) {
      showToast("Error: " + e.message, "danger");
      btn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------------------
// Settings page
// ---------------------------------------------------------------------------

function initSettings() {
  const form = document.getElementById("settings-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {};
    for (const [k, v] of fd.entries()) {
      // Always include path_maps (even empty, to allow clearing all mappings).
      // Skip other blank fields so we don't overwrite passwords with empty strings.
      if (v || k === "path_maps") payload[k] = v;
    }
    try {
      await api("POST", "/settings", payload);
      showToast("Settings saved", "success");
    } catch (e) {
      showToast("Error: " + e.message, "danger");
    }
  });
}

// ---------------------------------------------------------------------------
// Escape HTML helper
// ---------------------------------------------------------------------------

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  initQueue();
  initJobDetail();
  initAdd();
  initSettings();
});
