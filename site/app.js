const metricKeys = ["top@1", "top@3", "top@5", "avg@3", "avg@5", "mrr"];

const percent = value => `${(Number(value) * 100).toFixed(2)}%`;
const deltaText = value => `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)} pp`;

function metricCell(value, paperValue, primary = false) {
  const delta = paperValue == null ? null : value - paperValue;
  const outlier = delta != null && Math.abs(delta) > 0.05;
  return `<td class="${primary ? "primary" : ""}"><span class="metric">${percent(value)}</span>${delta == null ? "" : `<span class="delta ${outlier ? "outlier" : ""}">${deltaText(delta)}</span>`}</td>`;
}

async function render() {
  const response = await fetch("data.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Cannot load results: ${response.status}`);
  const data = await response.json();
  const latest = new Map();
  for (const entry of data.entries) latest.set(entry.algorithm, entry);
  const entries = [...latest.values()].sort((a, b) => b.metrics.mrr - a.metrics.mrr);
  const paper = data.paper_reference?.metrics ?? {};

  document.querySelector("#case-count").textContent = data.benchmark.dataset_cases.toLocaleString();
  document.querySelector("#updated-at").textContent = `Last update ${new Date(data.generated_at).toLocaleString()}`;
  document.querySelector("#leaderboard-body").innerHTML = entries.map((entry, index) => {
    const reference = paper[entry.algorithm] ?? {};
    const cells = metricKeys.map(key => metricCell(entry.metrics[key], reference[key], key === "mrr")).join("");
    return `<tr>
      <td><div class="method-name"><span class="rank">${String(index + 1).padStart(2, "0")}</span><span>${entry.display_name}<small class="commit">${entry.algorithm_commit.slice(0, 8)} · ${entry.cases} cases</small></span></div></td>
      <td>${entry.scope}</td>
      ${cells}
      <td>${entry.metrics.average_algorithm_seconds == null ? "—" : `${Number(entry.metrics.average_algorithm_seconds).toFixed(2)}s`}</td>
    </tr>`;
  }).join("");
}

render().catch(error => {
  document.querySelector("#leaderboard-body").innerHTML = `<tr><td colspan="9">${error.message}</td></tr>`;
});

