import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useCollectJobs } from "../context/CollectJobContext";
import type { DanbooruStatus, Series, SeriesCreatePayload } from "../types";
import { resolveSeriesStatus, seriesStatusBadgeClass } from "../utils/seriesStatus";

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
  const {
    startCollect,
    startAppearanceExtract,
    isProcessingSeries,
    isCollectingSeries,
    isExtractingAppearanceSeries,
    lastCompletedJob,
    clearLastCompletedJob,
  } = useCollectJobs();
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
  const [danbooruStatus, setDanbooruStatus] = useState<DanbooruStatus | null>(null);

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

  useEffect(() => {
    void api
      .getDanbooruStatus()
      .then(setDanbooruStatus)
      .catch(() => setDanbooruStatus(null));
  }, []);

  useEffect(() => {
    if (!lastCompletedJob) {
      return;
    }
    void loadSeries().finally(() => {
      clearLastCompletedJob();
    });
  }, [lastCompletedJob?.job_id]);

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
    setError(null);
    try {
      await startCollect(series.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to collect characters");
    }
  };

  const handleExtractAppearance = async (series: Series) => {
    setError(null);
    try {
      await startAppearanceExtract(series.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to extract appearance tags");
    }
  };

  const canExtractAppearance = (series: Series) => series.character_count > 0;

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

      {danbooruStatus ? (
        <div
          className={`danbooru-status ${
            danbooruStatus.ready ? "danbooru-status-ready" : "danbooru-status-error"
          }`}
        >
          {danbooruStatus.ready
            ? `Danbooru / pybooru 준비됨 (${danbooruStatus.username}, v${danbooruStatus.pybooru_version ?? "?"})`
            : danbooruStatus.message}
        </div>
      ) : null}

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
        {loading ? <div className="empty-state">Loading series...</div> : null}

        {!loading ? (
          <>
            <div className="catalog-card-subtitle" style={{ marginBottom: 12 }}>
              Total: {filteredCount}
            </div>
            <div style={{ overflowX: "auto" }}>
              <table className="data-table">
                <colgroup>
                  <col className="col-series-tag" />
                  <col className="col-display-name" />
                  <col className="col-count" />
                  <col className="col-count" />
                  <col className="col-last-collect" />
                  <col className="col-priority" />
                  <col className="col-status" />
                  <col className="col-note" />
                  <col className="col-actions" />
                </colgroup>
                <thead>
                  <tr>
                    <th className="col-series-tag">series_tag</th>
                    <th className="col-display-name">display_name</th>
                    <th className="col-count">post_count</th>
                    <th className="col-count">characters</th>
                    <th className="col-last-collect">last collect</th>
                    <th className="col-priority">priority</th>
                    <th className="col-status">status</th>
                    <th className="col-note">note</th>
                    <th className="col-actions">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((series) => (
                    <tr key={series.id}>
                      <td className="col-series-tag cell-ellipsis" title={series.series_tag}>
                        {series.series_tag}
                      </td>
                      <td className="col-display-name cell-ellipsis" title={series.display_name}>
                        {series.display_name}
                      </td>
                      <td className="col-count">{series.post_count.toLocaleString()}</td>
                      <td className="col-count">{series.character_count.toLocaleString()}</td>
                      <td className="col-last-collect">
                        {series.last_collect_created > 0 ? (
                          <span className="badge badge-success">+{series.last_collect_created.toLocaleString()}</span>
                        ) : (
                          "-"
                        )}
                        {series.last_collect_skipped > 0 ? (
                          <span className="catalog-card-subtitle" style={{ marginLeft: 8 }}>
                            skip {series.last_collect_skipped.toLocaleString()}
                          </span>
                        ) : null}
                      </td>
                      <td className="col-priority">{series.priority}</td>
                      <td className="col-status">
                        {(() => {
                          const displayStatus = resolveSeriesStatus(series);
                          return (
                            <span className={seriesStatusBadgeClass(displayStatus.tone)}>
                              {displayStatus.label}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="col-note cell-ellipsis" title={series.note || undefined}>
                        {series.note || "-"}
                      </td>
                      <td className="col-actions">
                        <div className="table-actions">
                          <button
                            className="btn btn-small btn-primary"
                            type="button"
                            disabled={
                              isProcessingSeries(series.id) || danbooruStatus?.ready === false
                            }
                            onClick={() => void handleCollectCharacters(series)}
                          >
                            {isCollectingSeries(series.id) ? "Collecting..." : "Collect"}
                          </button>
                          <button
                            className="btn btn-small"
                            type="button"
                            disabled={
                              !canExtractAppearance(series) ||
                              isProcessingSeries(series.id) ||
                              danbooruStatus?.ready === false
                            }
                            title={
                              canExtractAppearance(series)
                                ? "Danbooru related tags 기반 외형 태그 추출"
                                : "캐릭터 수집 완료 후 사용 가능"
                            }
                            onClick={() => void handleExtractAppearance(series)}
                          >
                            {isExtractingAppearanceSeries(series.id) ? "Extracting..." : "Appearance"}
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
