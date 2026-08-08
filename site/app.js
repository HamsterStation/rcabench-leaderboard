const metricKeys = new Set(["top@1", "top@3", "top@5", "avg@3", "avg@5", "mrr", "average_algorithm_seconds"]);
const repositoryUrl = "https://github.com/HamsterStation/rcabench-leaderboard";

const state = {
  boards: [],
  board: null,
  query: "",
  sortKey: "mrr",
  sortDirection: "desc",
};

const percent = value => `${(Number(value) * 100).toFixed(2)}%`;
const seconds = value => value == null ? "—" : `${Number(value).toFixed(2)}s`;
const activeSortClass = key => key === state.sortKey ? " active-sort" : "";
const escapeHtml = value => String(value).replace(/[&<>'"]/g, character => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "'": "&#39;",
  "\"": "&quot;",
})[character]);

function latestEntries(board) {
  const latest = new Map();
  for (const entry of board.entries) latest.set(entry.algorithm, entry);
  return [...latest.values()];
}

function entryValue(entry, key) {
  if (metricKeys.has(key)) return Number(entry.metrics[key] ?? Number.NEGATIVE_INFINITY);
  return String(entry[key] ?? "").toLocaleLowerCase();
}

function archiveUrl(entry, board) {
  const benchmarkDirectory = board.benchmark.id.startsWith("fse-") ? "fse" : "ops-lite";
  const path = `results/history/${entry.run_id}/${benchmarkDirectory}/${entry.algorithm}.json`;
  return `${repositoryUrl}/blob/main/${path}`;
}

function updateUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("benchmark", state.board.benchmark.id);
  if (state.query) url.searchParams.set("q", state.query);
  else url.searchParams.delete("q");
  if (state.sortKey !== "mrr") url.searchParams.set("sort", state.sortKey);
  else url.searchParams.delete("sort");
  if (state.sortDirection !== "desc") url.searchParams.set("direction", state.sortDirection);
  else url.searchParams.delete("direction");
  history.replaceState(null, "", url);
}

function renderRows() {
  const body = document.querySelector("#leaderboard-body");
  const direction = state.sortDirection === "asc" ? 1 : -1;
  const query = state.query.toLocaleLowerCase();
  const entries = latestEntries(state.board)
    .filter(entry => `${entry.display_name} ${entry.algorithm}`.toLocaleLowerCase().includes(query))
    .sort((left, right) => {
      const a = entryValue(left, state.sortKey);
      const b = entryValue(right, state.sortKey);
      const result = typeof a === "number" ? a - b : a.localeCompare(b);
      return result === 0 ? left.display_name.localeCompare(right.display_name) : result * direction;
    });

  document.querySelector("#result-count").textContent = `${entries.length} algorithm${entries.length === 1 ? "" : "s"}`;
  document.querySelectorAll(".sort-button").forEach(button => {
    const active = button.dataset.sort === state.sortKey;
    const heading = button.closest("th");
    heading.classList.toggle("active-sort", active);
    heading.setAttribute("aria-sort", active ? (state.sortDirection === "asc" ? "ascending" : "descending") : "none");
    button.querySelector("span").textContent = active ? (state.sortDirection === "asc" ? "↑" : "↓") : "";
  });

  if (!entries.length) {
    body.innerHTML = '<tr><td class="empty-state" colspan="11">No algorithms match this search.</td></tr>';
    return;
  }

  body.innerHTML = entries.map((entry, index) => `
    <tr>
      <td class="rank-column">${index + 1}</td>
      <td class="algorithm-column${activeSortClass("display_name")}">
        <div class="algorithm-name">${escapeHtml(entry.display_name)}</div>
        <div class="algorithm-meta"><code>${escapeHtml(entry.algorithm_commit.slice(0, 8))}</code> · ${Number(entry.cases).toLocaleString()} cases</div>
      </td>
      <td><span class="scope-badge">${escapeHtml(entry.scope)}</span></td>
      <td class="number${activeSortClass("top@1")}">${percent(entry.metrics["top@1"])}</td>
      <td class="number${activeSortClass("top@3")}">${percent(entry.metrics["top@3"])}</td>
      <td class="number${activeSortClass("top@5")}">${percent(entry.metrics["top@5"])}</td>
      <td class="number${activeSortClass("avg@3")}">${percent(entry.metrics["avg@3"])}</td>
      <td class="number${activeSortClass("avg@5")}">${percent(entry.metrics["avg@5"])}</td>
      <td class="number${activeSortClass("mrr")}">${percent(entry.metrics.mrr)}</td>
      <td class="number${activeSortClass("average_algorithm_seconds")}">${seconds(entry.metrics.average_algorithm_seconds)}</td>
      <td><a class="run-link" href="${archiveUrl(entry, state.board)}">Metrics <span aria-hidden="true">↗</span></a></td>
    </tr>`).join("");
}

function showBoard(board) {
  state.board = board;
  const entries = latestEntries(board);
  document.querySelector("#algorithm-count").textContent = entries.length.toLocaleString();
  document.querySelector("#case-count").textContent = board.benchmark.dataset_cases.toLocaleString();
  document.querySelector("#dataset-revision").textContent = board.benchmark.dataset_revision.slice(0, 10);
  document.querySelector("#dataset-revision").title = board.benchmark.dataset_revision;
  document.querySelector("#board-description").textContent = `${board.benchmark.title} · service-level evaluation`;
  document.querySelectorAll("#benchmark-tabs button").forEach(button => {
    const selected = button.dataset.id === board.benchmark.id;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  renderRows();
  updateUrl();
}

function bindControls() {
  document.querySelector("#benchmark-tabs").addEventListener("click", event => {
    const button = event.target.closest("button[data-id]");
    if (button) showBoard(state.boards.find(board => board.benchmark.id === button.dataset.id));
  });

  document.querySelector("#algorithm-search").addEventListener("input", event => {
    state.query = event.target.value.trim();
    renderRows();
    updateUrl();
  });

  document.querySelector("thead").addEventListener("click", event => {
    const button = event.target.closest("button[data-sort]");
    if (!button) return;
    if (state.sortKey === button.dataset.sort) {
      state.sortDirection = state.sortDirection === "desc" ? "asc" : "desc";
    } else {
      state.sortKey = button.dataset.sort;
      state.sortDirection = button.dataset.sort === "display_name" ? "asc" : "desc";
    }
    renderRows();
    updateUrl();
  });
}

async function render() {
  const response = await fetch("data.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Cannot load results: ${response.status}`);
  const data = await response.json();
  state.boards = data.benchmarks ?? [data];

  const params = new URLSearchParams(window.location.search);
  const requestedBoard = params.get("benchmark");
  const requestedSort = params.get("sort");
  if (requestedSort && (metricKeys.has(requestedSort) || requestedSort === "display_name")) state.sortKey = requestedSort;
  if (params.get("direction") === "asc") state.sortDirection = "asc";
  state.query = params.get("q") ?? "";

  document.querySelector("#algorithm-search").value = state.query;
  document.querySelector("#updated-at").textContent = `Last updated ${new Date(data.generated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`;
  document.querySelector("#benchmark-tabs").innerHTML = state.boards.map(board => `
    <button type="button" role="tab" data-id="${escapeHtml(board.benchmark.id)}">${escapeHtml(board.benchmark.title)}</button>`).join("");
  bindControls();
  showBoard(state.boards.find(board => board.benchmark.id === requestedBoard) ?? state.boards[0]);
}

render().catch(error => {
  document.querySelector("#leaderboard-body").innerHTML = `<tr><td class="empty-state" colspan="11">${escapeHtml(error.message)}</td></tr>`;
});
