import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CatalogFilters, CatalogItem, CatalogStats, Series } from "../types";
import { CatalogCard } from "../components/CatalogCard";

const PAGE_SIZE = 48;

const emptyStats: CatalogStats = {
  series_count: 0,
  character_count: 0,
  completed_count: 0,
  cover_image_count: 0,
};

export function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [stats, setStats] = useState<CatalogStats>(emptyStats);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [seriesOptions, setSeriesOptions] = useState<Series[]>([]);
  const [filters, setFilters] = useState<CatalogFilters>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seriesChangeTarget, setSeriesChangeTarget] = useState<CatalogItem | null>(null);
  const [seriesChangeId, setSeriesChangeId] = useState<number | null>(null);
  const [seriesChangeSearch, setSeriesChangeSearch] = useState("");
  const [seriesPickerItems, setSeriesPickerItems] = useState<Series[]>([]);
  const [seriesChangeSaving, setSeriesChangeSaving] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const activeFilterCount = useMemo(
    () =>
      Object.entries(filters).filter(
        ([key, value]) => !["skip", "limit"].includes(key) && value !== undefined && value !== "",
      ).length,
    [filters],
  );

  const loadData = async (targetPage = page) => {
    setLoading(true);
    setError(null);
    try {
      const query: CatalogFilters = {
        ...filters,
        skip: (targetPage - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      };
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
  };

  useEffect(() => {
    setPage(1);
  }, [filters]);

  useEffect(() => {
    void loadData(page);
  }, [filters, page]);

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

  const filteredSeriesOptions = seriesPickerItems;

  const handleSeriesChange = async (event: FormEvent) => {
    event.preventDefault();
    if (!seriesChangeTarget || !seriesChangeId) return;
    setSeriesChangeSaving(true);
    setError(null);
    try {
      await api.updateCharacterSeries(seriesChangeTarget.id, seriesChangeId);
      closeSeriesChangeModal();
      await loadData(page);
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
          <h1 className="page-title">Catalog Viewer</h1>
          <p className="page-description">
            수집/생성/검수 상태를 확인하고 작업 허브로 이동할 수 있는 메인 화면입니다.
          </p>
        </div>
        <button className="btn" type="button" onClick={() => void loadData(page)}>
          Refresh
        </button>
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

      <section className="panel">
        <div className="toolbar">
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
          <div className="field" style={{ justifyContent: "flex-end" }}>
            <label>&nbsp;</label>
            <button className="btn" type="button" onClick={() => updateFilters(() => ({}))}>
              Clear filters ({activeFilterCount})
            </button>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {loading ? <div className="empty-state">Loading catalog...</div> : null}
        {!loading && items.length === 0 ? (
          <div className="empty-state">표시할 캐릭터가 없습니다. Series를 추가하거나 Character Collector를 실행하세요.</div>
        ) : null}
        {!loading && items.length > 0 ? (
          <>
            <div className="catalog-grid">
              {items.map((item) => (
                <CatalogCard key={item.id} item={item} onChangeSeries={openSeriesChangeModal} />
              ))}
            </div>
            <div className="pagination-bar">
              <span className="catalog-card-subtitle">
                {total.toLocaleString()} results · page {page} / {totalPages}
              </span>
              <div className="card-actions">
                <button
                  className="btn btn-small"
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                >
                  Previous
                </button>
                <button
                  className="btn btn-small"
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        ) : null}
      </section>

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
                    {filteredSeriesOptions.map((series) => (
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
