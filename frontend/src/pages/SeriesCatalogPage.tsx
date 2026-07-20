import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, waitForBackend } from "../api/client";
import { useReviewRegenerateJobs } from "../context/ReviewRegenerateContext";
import type { CatalogFilters, CatalogItem, CatalogStats, Series } from "../types";
import { CatalogEditModal } from "../components/CatalogEditModal";
import { CatalogRandomPanel } from "../components/CatalogRandomPanel";
import { CatalogVirtualGrid } from "../components/CatalogVirtualGrid";

const PAGE_SIZE = 96;

const emptyStats: CatalogStats = {
  series_count: 0,
  character_count: 0,
  completed_count: 0,
  cover_image_count: 0,
};

function filterQuery(filters: CatalogFilters): Omit<CatalogFilters, "skip" | "limit"> {
  const { skip: _skip, limit: _limit, ...rest } = filters;
  return rest;
}

export function SeriesCatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<CatalogStats>(emptyStats);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [seriesOptions, setSeriesOptions] = useState<Series[]>([]);
  const [filters, setFilters] = useState<CatalogFilters>({});
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<CatalogItem | null>(null);
  const [seriesChangeTarget, setSeriesChangeTarget] = useState<CatalogItem | null>(null);
  const [seriesChangeId, setSeriesChangeId] = useState<number | null>(null);
  const [seriesChangeSearch, setSeriesChangeSearch] = useState("");
  const [seriesPickerItems, setSeriesPickerItems] = useState<Series[]>([]);
  const [seriesChangeSaving, setSeriesChangeSaving] = useState(false);
  const {
    jobs,
    enqueueRegenerate,
    isCharacterRegenerating,
    lastCompletedJob,
    clearLastCompletedJob,
  } = useReviewRegenerateJobs();

  const activeRegenerateJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running"),
    [jobs],
  );

  const listFilters = useMemo(() => filterQuery(filters), [filters]);

  const activeFilterCount = useMemo(
    () =>
      Object.entries(filters).filter(
        ([key, value]) => !["skip", "limit"].includes(key) && value !== undefined && value !== "",
      ).length,
    [filters],
  );

  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await waitForBackend();
      const query: CatalogFilters = { ...listFilters, skip: 0, limit: PAGE_SIZE };
      const [catalog, catalogStats, catalogStatuses, seriesList] = await Promise.all([
        api.listCatalog(query),
        api.getCatalogStats(),
        api.getCatalogStatuses(),
        api.listSeries({ sort_by: "post_count", sort_order: "desc", limit: 500 }),
      ]);
      setItems(catalog.items);
      setTotal(catalog.total);
      setStats(catalogStats);
      setStatuses(catalogStatuses);
      setSeriesOptions(seriesList.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load catalog");
    } finally {
      setLoading(false);
    }
  }, [listFilters]);

  const loadMore = useCallback(async () => {
    if (loading || loadingMore || items.length >= total) {
      return;
    }
    setLoadingMore(true);
    try {
      const response = await api.listCatalog({
        ...listFilters,
        skip: items.length,
        limit: PAGE_SIZE,
      });
      setItems((current) => {
        const existing = new Set(current.map((entry) => entry.id));
        const appended = response.items.filter((entry) => !existing.has(entry.id));
        return [...current, ...appended];
      });
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more catalog items");
    } finally {
      setLoadingMore(false);
    }
  }, [items.length, listFilters, loading, loadingMore, total]);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  useEffect(() => {
    if (!seriesChangeTarget) return;
    const timer = window.setTimeout(() => {
      void api
        .listSeries({
          search: seriesChangeSearch || undefined,
          sort_by: "post_count",
          sort_order: "desc",
          limit: 100,
        })
        .then((response) => setSeriesPickerItems(response.items))
        .catch(() => setSeriesPickerItems([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [seriesChangeTarget, seriesChangeSearch]);

  const updateFilters = (updater: (prev: CatalogFilters) => CatalogFilters) => {
    setFilters(updater);
  };

  const handleItemSaved = (updated: CatalogItem) => {
    setItems((current) => current.map((entry) => (entry.id === updated.id ? updated : entry)));
  };

  const handleRegenerate = async (item: CatalogItem) => {
    const prompt = item.final_prompt || item.generation_prompt;
    if (!prompt?.trim()) {
      setError("재생성할 프롬프트가 없습니다.");
      return;
    }
    if (isCharacterRegenerating(item.id, "series")) {
      setExportMessage(`${item.character_tag} 재생성이 이미 진행 중입니다.`);
      return;
    }
    setError(null);
    try {
      const job = await enqueueRegenerate(item.id, {
        prompt,
        gender: item.gender,
      });
      setExportMessage(job.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to regenerate images");
    }
  };

  useEffect(() => {
    if (!lastCompletedJob?.result) {
      return;
    }
    if (lastCompletedJob.scope !== "series") {
      return;
    }
    setExportMessage(
      `${lastCompletedJob.character_tag} 이미지 ${lastCompletedJob.result.images.length}장 재생성 완료`,
    );
    void loadInitial();
    clearLastCompletedJob();
  }, [clearLastCompletedJob, lastCompletedJob, loadInitial]);

  const handleExport = async () => {
    setError(null);
    setExportMessage(null);
    try {
      const result = await api.exportCatalogCsv(listFilters);
      const blob = new Blob([result.content], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "catalog-export.csv";
      link.click();
      URL.revokeObjectURL(url);
      setExportMessage(
        result.savedPath
          ? `CSV를 다운로드했고 ${result.savedPath} 에도 저장했습니다.`
          : "CSV를 다운로드했습니다.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export catalog CSV");
    }
  };

  const openSeriesChangeModal = (item: CatalogItem) => {
    setSeriesChangeTarget(item);
    setSeriesChangeId(null);
    setSeriesChangeSearch("");
    setError(null);
  };

  const closeSeriesChangeModal = () => {
    setSeriesChangeTarget(null);
    setSeriesChangeId(null);
    setSeriesChangeSearch("");
    setSeriesChangeSaving(false);
  };

  const handleSeriesChange = async (event: FormEvent) => {
    event.preventDefault();
    if (!seriesChangeTarget || !seriesChangeId) return;
    setSeriesChangeSaving(true);
    setError(null);
    try {
      await api.updateCharacterSeries(seriesChangeTarget.id, seriesChangeId);
      closeSeriesChangeModal();
      await loadInitial();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to change series");
    } finally {
      setSeriesChangeSaving(false);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Series Catalog (구버전)</h1>
          <p className="page-description">
            시리즈 기반으로 수집·생성·검수된 캐릭터를 탐색하고, 필터·랜덤 확인·인라인 수정으로 카탈로그를 관리합니다.
          </p>
        </div>
        <div className="card-actions">
          <button className="btn" type="button" onClick={() => void handleExport()}>
            Export CSV
          </button>
          <button className="btn" type="button" onClick={() => void loadInitial()}>
            Refresh
          </button>
        </div>
      </div>

      <div className="stats-row">
        <div className="stat-card">
          <div className="stat-label">Series</div>
          <div className="stat-value">{stats.series_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Characters</div>
          <div className="stat-value">{stats.character_count.toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Completed</div>
          <div className="stat-value">{stats.completed_count.toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Cover Images</div>
          <div className="stat-value">{stats.cover_image_count.toLocaleString()}</div>
        </div>
      </div>

      <CatalogRandomPanel filters={listFilters} />

      <section className="panel">
        <div className="toolbar catalog-toolbar">
          <div className="field">
            <label htmlFor="search">Search</label>
            <input
              id="search"
              value={filters.search ?? ""}
              onChange={(event) => updateFilters((prev) => ({ ...prev, search: event.target.value }))}
              placeholder="character / series"
            />
          </div>
          <div className="field">
            <label htmlFor="series">Series</label>
            <select
              id="series"
              value={filters.series_tag ?? ""}
              onChange={(event) =>
                updateFilters((prev) => ({ ...prev, series_tag: event.target.value || undefined }))
              }
            >
              <option value="">All</option>
              {seriesOptions.map((series) => (
                <option key={series.series_tag} value={series.series_tag}>
                  {series.series_tag}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="gender">Gender</label>
            <select
              id="gender"
              value={filters.gender ?? ""}
              onChange={(event) =>
                updateFilters((prev) => ({ ...prev, gender: event.target.value || undefined }))
              }
            >
              <option value="">All</option>
              <option value="1girl">1girl</option>
              <option value="1boy">1boy</option>
              <option value="no_humans">no_humans</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="rating">Rating</label>
            <select
              id="rating"
              value={filters.rating === undefined ? "" : String(filters.rating)}
              onChange={(event) => {
                const value = event.target.value;
                updateFilters((prev) => ({
                  ...prev,
                  rating: value === "" ? undefined : Number(value),
                }));
              }}
            >
              <option value="">All</option>
              <option value="-1">-1</option>
              {Array.from({ length: 7 }, (_, index) => (
                <option key={index} value={String(index)}>
                  {index}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="type">Type</label>
            <input
              id="type"
              value={filters.type ?? ""}
              onChange={(event) => updateFilters((prev) => ({ ...prev, type: event.target.value || undefined }))}
              placeholder="type"
            />
          </div>
          <div className="field">
            <label htmlFor="hair_color">Hair</label>
            <input
              id="hair_color"
              value={filters.hair_color ?? ""}
              onChange={(event) =>
                updateFilters((prev) => ({ ...prev, hair_color: event.target.value || undefined }))
              }
              placeholder="hair color"
            />
          </div>
          <div className="field">
            <label htmlFor="eye_color">Eyes</label>
            <input
              id="eye_color"
              value={filters.eye_color ?? ""}
              onChange={(event) =>
                updateFilters((prev) => ({ ...prev, eye_color: event.target.value || undefined }))
              }
              placeholder="eye color"
            />
          </div>
          <div className="field">
            <label htmlFor="feature_tags">Features</label>
            <input
              id="feature_tags"
              value={filters.feature_tags ?? ""}
              onChange={(event) =>
                updateFilters((prev) => ({ ...prev, feature_tags: event.target.value || undefined }))
              }
              placeholder="feature tags"
            />
          </div>
          <div className="field">
            <label htmlFor="status">Catalog Status</label>
            <select
              id="status"
              value={filters.status ?? ""}
              onChange={(event) =>
                updateFilters((prev) => ({ ...prev, status: event.target.value || undefined }))
              }
            >
              <option value="">All</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="has_cover">Cover Image</label>
            <select
              id="has_cover"
              value={filters.has_cover_image === undefined ? "" : String(filters.has_cover_image)}
              onChange={(event) => {
                const value = event.target.value;
                updateFilters((prev) => ({
                  ...prev,
                  has_cover_image: value === "" ? undefined : value === "true",
                }));
              }}
            >
              <option value="">All</option>
              <option value="true">Has cover</option>
              <option value="false">Missing cover</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="needs_review">Needs Review</label>
            <select
              id="needs_review"
              value={filters.needs_review === undefined ? "" : String(filters.needs_review)}
              onChange={(event) => {
                const value = event.target.value;
                updateFilters((prev) => ({
                  ...prev,
                  needs_review: value === "" ? undefined : value === "true",
                }));
              }}
            >
              <option value="">All</option>
              <option value="true">Yes</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="needs_regen">Needs Regen</label>
            <select
              id="needs_regen"
              value={filters.needs_regen === undefined ? "" : String(filters.needs_regen)}
              onChange={(event) => {
                const value = event.target.value;
                updateFilters((prev) => ({
                  ...prev,
                  needs_regen: value === "" ? undefined : value === "true",
                }));
              }}
            >
              <option value="">All</option>
              <option value="true">Yes</option>
            </select>
          </div>
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <label>&nbsp;</label>
            <button className="btn" type="button" onClick={() => updateFilters(() => ({}))}>
              Clear filters ({activeFilterCount})
            </button>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {exportMessage ? <div className="success-banner">{exportMessage}</div> : null}
        {activeRegenerateJobs.length > 0 ? (
          <div className="catalog-card-subtitle">
            재생성 {activeRegenerateJobs.length}건 진행 중...
          </div>
        ) : null}

        <CatalogVirtualGrid
          items={items}
          total={total}
          loading={loading}
          loadingMore={loadingMore}
          onLoadMore={() => void loadMore()}
          onEdit={setEditTarget}
          onChangeSeries={openSeriesChangeModal}
          onRegenerate={(item) => void handleRegenerate(item)}
        />
      </section>

      {editTarget ? (
        <CatalogEditModal item={editTarget} onClose={() => setEditTarget(null)} onSaved={handleItemSaved} />
      ) : null}

      {seriesChangeTarget ? (
        <div className="modal-backdrop" onClick={closeSeriesChangeModal}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <h2 className="modal-title">Change Series</h2>
            <p className="page-description">
              {seriesChangeTarget.character_tag} · current: {seriesChangeTarget.series_tag}
            </p>
            <form onSubmit={(event) => void handleSeriesChange(event)}>
              <div className="form-grid">
                <div className="field full-width">
                  <label htmlFor="series-change-search">Search series</label>
                  <input
                    id="series-change-search"
                    value={seriesChangeSearch}
                    onChange={(event) => setSeriesChangeSearch(event.target.value)}
                    placeholder="series tag"
                  />
                </div>
                <div className="field full-width">
                  <label htmlFor="series-change-target">Target series</label>
                  <select
                    id="series-change-target"
                    required
                    value={seriesChangeId ?? ""}
                    onChange={(event) => setSeriesChangeId(Number(event.target.value))}
                  >
                    <option value="">Select series</option>
                    {seriesPickerItems.map((series) => (
                      <option key={series.id} value={series.id}>
                        {series.series_tag} · {series.display_name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="modal-actions">
                <button className="btn" type="button" onClick={closeSeriesChangeModal}>
                  Cancel
                </button>
                <button className="btn btn-primary" type="submit" disabled={!seriesChangeId || seriesChangeSaving}>
                  {seriesChangeSaving ? "Saving..." : "Save"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
