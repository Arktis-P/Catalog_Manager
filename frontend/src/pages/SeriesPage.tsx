import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { SeriesCharactersModal } from "../components/SeriesCharactersModal";
import { isSeriesMergeEligible, SeriesMergeModal } from "../components/SeriesMergeModal";
import { useCollectJobs } from "../context/CollectJobContext";
import type { DanbooruStatus, Series, SeriesCreatePayload } from "../types";
import { downloadTextFile } from "../utils/download";
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
  const [viewingSeries, setViewingSeries] = useState<Series | null>(null);
  const [mergingSeriesList, setMergingSeriesList] = useState<Series[] | null>(null);
  const [selectedMergeIds, setSelectedMergeIds] = useState<Set<number>>(() => new Set());
  const [expandedParentIds, setExpandedParentIds] = useState<Set<number>>(() => new Set());
  const [exportingCharacters, setExportingCharacters] = useState(false);

  const mergeEligibleItems = useMemo(
    () => items.filter((series) => isSeriesMergeEligible(series)),
    [items],
  );

  const hiddenChildCount = useMemo(
    () =>
      items.filter(
        (series) =>
          series.is_merged_child &&
          series.parent_series_id !== null &&
          !expandedParentIds.has(series.parent_series_id),
      ).length,
    [items, expandedParentIds],
  );

  const visibleItems = useMemo(() => {
    const visible: Series[] = [];
    for (const series of items) {
      if (series.is_merged_child) {
        if (series.parent_series_id && expandedParentIds.has(series.parent_series_id)) {
          visible.push(series);
        }
        continue;
      }
      visible.push(series);
    }
    return visible;
  }, [items, expandedParentIds]);

  const filteredCount = useMemo(() => visibleItems.length, [visibleItems]);

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
          limit: 500,
          hierarchical: true,
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
    if (!search.trim()) {
      return;
    }
    const parentsToExpand = new Set<number>();
    for (const series of items) {
      if (series.is_merged_child && series.parent_series_id) {
        parentsToExpand.add(series.parent_series_id);
      }
    }
    if (parentsToExpand.size === 0) {
      return;
    }
    setExpandedParentIds((current) => {
      const next = new Set(current);
      let changed = false;
      for (const parentId of parentsToExpand) {
        if (!next.has(parentId)) {
          next.add(parentId);
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [search, items]);

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

  const handleUnmerge = async (series: Series) => {
    if (!window.confirm(`Unmerge "${series.series_tag}" from "${series.parent_series_tag}"?`)) return;
    setError(null);
    try {
      await api.unmergeSeries(series.id);
      await loadSeries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to unmerge series");
    }
  };

  const resolveViewingSeries = (series: Series): Series => {
    if (!series.is_merged_child) {
      return series;
    }
    const parent = items.find((item) => item.id === series.parent_series_id);
    return parent ?? series;
  };

  const formatCharacterCount = (series: Series) => {
    if (series.is_merged_child) {
      const dup =
        series.merged_duplicate_count > 0
          ? ` · dup ${series.merged_duplicate_count.toLocaleString()}`
          : "";
      return `${series.merged_moved_count.toLocaleString()}${dup}`;
    }
    const merged = series.child_count > 0 ? ` · +${series.child_count}m` : "";
    return `${series.character_count.toLocaleString()}${merged}`;
  };

  const formatLastCollect = (series: Series) => {
    if (series.last_collect_created <= 0 && series.last_collect_skipped <= 0) {
      return "-";
    }
    const created =
      series.last_collect_created > 0 ? `+${series.last_collect_created.toLocaleString()}` : "";
    const skipped =
      series.last_collect_skipped > 0 ? `s${series.last_collect_skipped.toLocaleString()}` : "";
    return [created, skipped].filter(Boolean).join(" · ");
  };

  const canExtractAppearance = (series: Series) =>
    !series.is_merged_child && series.character_count > 0;

  const handleDelete = async (series: Series) => {
    if (!window.confirm(`Delete series "${series.series_tag}"?`)) return;
    try {
      await api.deleteSeries(series.id);
      await loadSeries();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete series");
    }
  };

  const handleExportSeries = async () => {
    try {
      const csv = await api.exportSeriesCsv();
      downloadTextFile(csv, "series.csv");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export series CSV");
    }
  };

  const handleExportCharacters = async () => {
    setExportingCharacters(true);
    setError(null);
    try {
      const csv = await api.exportCharactersCsv({
        search: search || undefined,
      });
      downloadTextFile(csv, "characters.csv");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export characters CSV");
    } finally {
      setExportingCharacters(false);
    }
  };

  const toggleMergeSelection = (seriesId: number) => {
    setSelectedMergeIds((current) => {
      const next = new Set(current);
      if (next.has(seriesId)) {
        next.delete(seriesId);
      } else {
        next.add(seriesId);
      }
      return next;
    });
  };

  const toggleAllMergeSelection = () => {
    setSelectedMergeIds((current) =>
      current.size === mergeEligibleItems.length
        ? new Set()
        : new Set(mergeEligibleItems.map((item) => item.id)),
    );
  };

  const toggleExpandedChildren = (parentId: number) => {
    setExpandedParentIds((current) => {
      const next = new Set(current);
      if (next.has(parentId)) {
        next.delete(parentId);
      } else {
        next.add(parentId);
      }
      return next;
    });
  };

  const openMergeModal = (series: Series) => {
    const selected = mergeEligibleItems.filter((item) => selectedMergeIds.has(item.id));
    if (selectedMergeIds.has(series.id) && selected.length > 1) {
      setMergingSeriesList(selected);
      return;
    }
    setMergingSeriesList([series]);
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
          <button className="btn" type="button" onClick={() => void handleExportSeries()}>
            Export Series CSV
          </button>
          <button
            className="btn"
            type="button"
            disabled={exportingCharacters}
            onClick={() => void handleExportCharacters()}
          >
            {exportingCharacters ? "Exporting..." : "Export Characters CSV"}
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
              표시: {filteredCount.toLocaleString()}
              {hiddenChildCount > 0 ? ` · 하위 시리즈 ${hiddenChildCount.toLocaleString()}개 숨김` : null}
            </div>
            <div className="series-table-scroll">
              <table className="data-table series-table">
                <colgroup>
                  <col className="col-checkbox" />
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
                    <th className="col-checkbox">
                      {mergeEligibleItems.length > 0 ? (
                        <input
                          type="checkbox"
                          aria-label="Select all merge-eligible series"
                          checked={
                            mergeEligibleItems.length > 0 &&
                            selectedMergeIds.size === mergeEligibleItems.length
                          }
                          onChange={toggleAllMergeSelection}
                        />
                      ) : null}
                    </th>
                    <th className="col-series-tag">series_tag</th>
                    <th className="col-display-name">display_name</th>
                    <th className="col-count">posts</th>
                    <th className="col-count">chars</th>
                    <th className="col-last-collect">collect</th>
                    <th className="col-priority">pri</th>
                    <th className="col-status">status</th>
                    <th className="col-note">note</th>
                    <th className="col-actions">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleItems.map((series) => (
                    <tr key={series.id} className={series.is_merged_child ? "series-child-row" : undefined}>
                      <td className="col-checkbox">
                        {isSeriesMergeEligible(series) ? (
                          <input
                            type="checkbox"
                            aria-label={`Select ${series.series_tag} for merge`}
                            checked={selectedMergeIds.has(series.id)}
                            onChange={() => toggleMergeSelection(series.id)}
                          />
                        ) : null}
                      </td>
                      <td className="col-series-tag cell-ellipsis" title={series.series_tag}>
                        <div className="series-tag-cell">
                          {!series.is_merged_child && series.child_count > 0 ? (
                            <button
                              type="button"
                              className="series-children-toggle"
                              aria-expanded={expandedParentIds.has(series.id)}
                              aria-label={
                                expandedParentIds.has(series.id)
                                  ? `Hide ${series.child_count} merged sub-series`
                                  : `Show ${series.child_count} merged sub-series`
                              }
                              title={
                                expandedParentIds.has(series.id)
                                  ? "하위 시리즈 숨기기"
                                  : "하위 시리즈 보기"
                              }
                              onClick={() => toggleExpandedChildren(series.id)}
                            >
                              <span className="series-children-toggle-icon" aria-hidden="true">
                                {expandedParentIds.has(series.id) ? "▼" : "▶"}
                              </span>
                              <span className="series-children-toggle-count">{series.child_count}</span>
                            </button>
                          ) : null}
                          <span className={series.is_merged_child ? "series-child-tag" : undefined}>
                            {series.is_merged_child ? `└ ${series.series_tag}` : series.series_tag}
                          </span>
                        </div>
                      </td>
                      <td className="col-display-name cell-ellipsis" title={series.display_name}>
                        {series.display_name}
                      </td>
                      <td className="col-count series-cell-nowrap">{series.post_count.toLocaleString()}</td>
                      <td
                        className="col-count series-cell-nowrap"
                        title={
                          series.is_merged_child
                            ? series.merged_duplicate_count > 0
                              ? `병합 시 중복 제외 ${series.merged_duplicate_count.toLocaleString()}`
                              : undefined
                            : series.child_count > 0
                              ? `하위 시리즈 ${series.child_count}개 병합 포함`
                              : undefined
                        }
                      >
                        {formatCharacterCount(series)}
                      </td>
                      <td className="col-last-collect series-cell-nowrap" title={formatLastCollect(series)}>
                        {formatLastCollect(series)}
                      </td>
                      <td className="col-priority series-cell-nowrap">{series.priority}</td>
                      <td className="col-status series-cell-nowrap">
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
                          {series.is_merged_child ? (
                            <>
                              <button
                                className="btn btn-small"
                                type="button"
                                onClick={() => void handleUnmerge(series)}
                              >
                                Unmerge
                              </button>
                              <button className="btn btn-small" type="button" onClick={() => openEditModal(series)}>
                                Edit
                              </button>
                            </>
                          ) : (
                            <>
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
                              <button
                                className="btn btn-small"
                                type="button"
                                disabled={series.character_count <= 0}
                                title={
                                  series.character_count > 0
                                    ? "수집된 캐릭터 목록과 외형 태그 보기"
                                    : "캐릭터 수집 후 사용 가능"
                                }
                                onClick={() => setViewingSeries(series)}
                              >
                                Characters
                              </button>
                              {isSeriesMergeEligible(series) ? (
                                <button
                                  className="btn btn-small"
                                  type="button"
                                  onClick={() => openMergeModal(series)}
                                >
                                  Merge
                                </button>
                              ) : null}
                              <button className="btn btn-small" type="button" onClick={() => openEditModal(series)}>
                                Edit
                              </button>
                              <button
                                className="btn btn-small btn-danger"
                                type="button"
                                onClick={() => void handleDelete(series)}
                              >
                                Delete
                              </button>
                            </>
                          )}
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

      {viewingSeries ? (
        <SeriesCharactersModal
          series={resolveViewingSeries(viewingSeries)}
          onClose={() => setViewingSeries(null)}
        />
      ) : null}
      {mergingSeriesList ? (
        <SeriesMergeModal
          seriesList={mergingSeriesList}
          onClose={() => setMergingSeriesList(null)}
          onMerged={() => {
            setSelectedMergeIds(new Set());
            void loadSeries();
          }}
        />
      ) : null}
    </>
  );
}
