import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Series, SeriesCreatePayload } from "../types";

type ModalMode = "create" | "edit";

const emptyForm: SeriesCreatePayload = {
  series_tag: "",
  display_name: "",
  post_count: 0,
  priority: 0,
  status: "pending",
  note: "",
};

export function SeriesPage() {
  const [items, setItems] = useState<Series[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalMode, setModalMode] = useState<ModalMode | null>(null);
  const [editingSeries, setEditingSeries] = useState<Series | null>(null);
  const [form, setForm] = useState<SeriesCreatePayload>(emptyForm);
  const [importReplace, setImportReplace] = useState(false);
  const [collectingSeriesId, setCollectingSeriesId] = useState<number | null>(null);
  const [collectMessage, setCollectMessage] = useState<string | null>(null);

  const filteredCount = useMemo(() => items.length, [items]);

  const loadSeries = async () => {
    setLoading(true);
    setError(null);
    try {
      const [seriesResponse, statusList] = await Promise.all([
        api.listSeries({
          search: search || undefined,
          status: statusFilter || undefined,
          sort_by: "post_count",
          sort_order: "desc",
        }),
        api.getSeriesStatuses(),
      ]);
      setItems(seriesResponse.items);
      setStatuses(statusList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load series");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSeries();
  }, [search, statusFilter]);

  const openCreateModal = () => {
    setModalMode("create");
    setEditingSeries(null);
    setForm(emptyForm);
  };

  const openEditModal = (series: Series) => {
    setModalMode("edit");
    setEditingSeries(series);
    setForm({
      series_tag: series.series_tag,
      display_name: series.display_name,
      post_count: series.post_count,
      priority: series.priority,
      status: series.status,
      note: series.note ?? "",
    });
  };

  const closeModal = () => {
    setModalMode(null);
    setEditingSeries(null);
    setForm(emptyForm);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      if (modalMode === "create") {
        await api.createSeries(form);
      } else if (editingSeries) {
        await api.updateSeries(editingSeries.id, form);
      }
      closeModal();
      await loadSeries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save series");
    }
  };

  const handleCollectCharacters = async (series: Series) => {
    setCollectingSeriesId(series.id);
    setCollectMessage(null);
    setError(null);
    try {
      const result = await api.collectCharactersForSeries(series.id);
      setCollectMessage(
        `${result.series_tag}: discovered ${result.discovered}, added ${result.created}, skipped ${result.skipped_existing}`,
      );
      await loadSeries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to collect characters");
    } finally {
      setCollectingSeriesId(null);
    }
  };

  const handleDelete = async (series: Series) => {
    if (!window.confirm(`Delete series "${series.series_tag}"?`)) return;
    try {
      await api.deleteSeries(series.id);
      await loadSeries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete series");
    }
  };

  const handleExport = async () => {
    try {
      const csv = await api.exportSeriesCsv();
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "series.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export CSV");
    }
  };

  const handleImport = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const result = await api.importSeriesCsv(file, importReplace);
      alert(
        `Import complete: created ${result.created}, updated ${result.updated}` +
          (result.merged_duplicates ? `, merged duplicates ${result.merged_duplicates}` : ""),
      );
      await loadSeries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import CSV");
    } finally {
      event.target.value = "";
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Series Manager</h1>
          <p className="page-description">Danbooru copyright tag 기준 시리즈 목록을 관리합니다.</p>
        </div>
        <div className="card-actions">
          <button className="btn btn-primary" type="button" onClick={openCreateModal}>
            Add Series
          </button>
          <button className="btn" type="button" onClick={() => void handleExport()}>
            Export CSV
          </button>
          <label className="btn">
            Import CSV
            <input type="file" accept=".csv" hidden onChange={(event) => void handleImport(event)} />
          </label>
        </div>
      </div>

      <section className="panel">
        <div className="toolbar">
          <div className="field">
            <label htmlFor="series-search">Search</label>
            <input
              id="series-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="series tag / display name"
            />
          </div>
          <div className="field">
            <label htmlFor="series-status">Status</label>
            <select id="series-status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">All</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="import-replace">Import mode</label>
            <select
              id="import-replace"
              value={String(importReplace)}
              onChange={(event) => setImportReplace(event.target.value === "true")}
            >
              <option value="false">Merge</option>
              <option value="true">Replace all</option>
            </select>
          </div>
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <label>&nbsp;</label>
            <button className="btn" type="button" onClick={() => void loadSeries()}>
              Refresh
            </button>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {collectMessage ? <div className="stat-card" style={{ marginBottom: 16 }}>{collectMessage}</div> : null}
        {loading ? <div className="empty-state">Loading series...</div> : null}

        {!loading ? (
          <>
            <div className="catalog-card-subtitle" style={{ marginBottom: 12 }}>
              Total: {filteredCount}
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>series_tag</th>
                    <th>display_name</th>
                    <th>post_count</th>
                    <th>priority</th>
                    <th>status</th>
                    <th>note</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((series) => (
                    <tr key={series.id}>
                      <td>{series.series_tag}</td>
                      <td>{series.display_name}</td>
                      <td>{series.post_count.toLocaleString()}</td>
                      <td>{series.priority}</td>
                      <td>
                        <span className="badge">{series.status}</span>
                      </td>
                      <td>{series.note || "-"}</td>
                      <td>
                        <div className="table-actions">
                          <button
                            className="btn btn-small btn-primary"
                            type="button"
                            disabled={collectingSeriesId === series.id}
                            onClick={() => void handleCollectCharacters(series)}
                          >
                            {collectingSeriesId === series.id ? "Collecting..." : "Collect"}
                          </button>
                          <button className="btn btn-small" type="button" onClick={() => openEditModal(series)}>
                            Edit
                          </button>
                          <button className="btn btn-small btn-danger" type="button" onClick={() => void handleDelete(series)}>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      {modalMode ? (
        <div className="modal-backdrop" onClick={closeModal}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h2 className="modal-title">{modalMode === "create" ? "Add Series" : "Edit Series"}</h2>
            <form onSubmit={(event) => void handleSubmit(event)}>
              <div className="form-grid">
                <div className="field full-width">
                  <label htmlFor="series_tag">series_tag</label>
                  <input
                    id="series_tag"
                    required
                    value={form.series_tag}
                    onChange={(event) => setForm((prev) => ({ ...prev, series_tag: event.target.value }))}
                  />
                </div>
                <div className="field full-width">
                  <label htmlFor="display_name">display_name</label>
                  <input
                    id="display_name"
                    value={form.display_name ?? ""}
                    onChange={(event) => setForm((prev) => ({ ...prev, display_name: event.target.value }))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="post_count">post_count</label>
                  <input
                    id="post_count"
                    type="number"
                    min={0}
                    value={form.post_count ?? 0}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, post_count: Number(event.target.value) }))
                    }
                  />
                </div>
                <div className="field">
                  <label htmlFor="priority">priority</label>
                  <input
                    id="priority"
                    type="number"
                    value={form.priority ?? 0}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, priority: Number(event.target.value) }))
                    }
                  />
                </div>
                <div className="field">
                  <label htmlFor="status">status</label>
                  <select
                    id="status"
                    value={form.status ?? "pending"}
                    onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value }))}
                  >
                    {statuses.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field full-width">
                  <label htmlFor="note">note</label>
                  <textarea
                    id="note"
                    rows={3}
                    value={form.note ?? ""}
                    onChange={(event) => setForm((prev) => ({ ...prev, note: event.target.value }))}
                  />
                </div>
              </div>
              <div className="modal-actions">
                <button className="btn" type="button" onClick={closeModal}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit">
                  Save
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
