const ids = Object.fromEntries([
  "freshness", "data-through", "line", "shift", "window", "oee",
  "availability", "performance", "quality", "downtime-total", "pareto",
  "total-count", "good-count", "rejected-count", "downtime-events", "warnings",
  "line-stop-time", "status-dot",
].map((id) => [id, document.getElementById(id)]));

const pct = (value) => value == null ? "N/A" : `${(Number(value) * 100).toFixed(1)}%`;
const integer = new Intl.NumberFormat("en-US");
const dateTime = new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" });
const duration = (seconds) => seconds >= 3600
  ? `${(seconds / 3600).toFixed(1)} h`
  : `${Math.round(seconds / 60)} min`;

function render(data) {
  ids["status-dot"].className = `status-dot ${data.freshness}`;
  ids.freshness.textContent = data.freshness === "fresh" ? "Data current" : "Data delayed";
  ids["data-through"].textContent = `Through ${dateTime.format(new Date(data.data_through))}`;
  ids.line.textContent = `${data.line.code} / ${data.line.name}`;
  ids.shift.textContent = `Shift ${data.window.shift}`;
  ids.window.textContent = `${dateTime.format(new Date(data.window.start))} - ${dateTime.format(new Date(data.window.end))}`;
  ids.oee.textContent = pct(data.oee);
  ids.availability.textContent = pct(data.availability);
  ids.performance.textContent = pct(data.performance_capped);
  ids.quality.textContent = pct(data.quality);
  ids["downtime-total"].textContent = duration(data.downtime_logged_event_seconds);
  ids["total-count"].textContent = integer.format(data.total_count);
  ids["good-count"].textContent = integer.format(data.good_count);
  ids["rejected-count"].textContent = integer.format(data.rejected_count);
  ids["line-stop-time"].textContent = duration(data.downtime_line_seconds);
  ids["downtime-events"].textContent = integer.format(data.downtime_total_events);
  ids.pareto.replaceChildren(...data.top_reasons.map((item) => {
    const row = document.createElement("div");
    row.className = "pareto-row";
    const label = document.createElement("span");
    label.textContent = item.reason;
    const track = document.createElement("div");
    track.className = "bar-track";
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.width = `${Math.max(2, Number(item.share) * 100)}%`;
    track.append(bar);
    const value = document.createElement("span");
    value.className = "pareto-value";
    value.textContent = duration(item.seconds);
    row.append(label, track, value);
    return row;
  }));
  if (!data.top_reasons.length) ids.pareto.textContent = "No downtime recorded in this window.";
  const warnings = data.warnings.length ? data.warnings : ["NO_ACTIVE_WARNINGS"];
  ids.warnings.replaceChildren(...warnings.map((warning) => {
    const badge = document.createElement("span");
    badge.className = warning === "NO_ACTIVE_WARNINGS" ? "warning ok" : "warning";
    badge.textContent = warning.replaceAll("_", " ");
    return badge;
  }));
}

async function refresh() {
  try {
    const response = await fetch("/api/v1/demo/overview", { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (_) {
    ids["status-dot"].className = "status-dot error";
    ids.freshness.textContent = "Demo warming up";
    ids["data-through"].textContent = "The service or data source is temporarily unavailable. Retrying automatically.";
  }
}

refresh();
window.setInterval(refresh, 60_000);
