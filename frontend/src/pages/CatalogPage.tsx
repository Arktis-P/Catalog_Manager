import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CatalogFilters, CatalogItem, CatalogStats } from "../types";
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
  const [seriesOptions, setSeriesOptions] = useState<string[]>([]);
  const [filters, setFilters] = useState<CatalogFilters>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      setSeriesOptions(seriesList.items.map((series) => series.series_tag));
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

  const updateFilters = (updater: (prev: CatalogFilters) => CatalogFilters) => {
    setFilters(updater);
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
              {seriesOptions.map((seriesTag) => (
                <option key={seriesTag} value={seriesTag}>
                  {seriesTag}
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
                <CatalogCard key={item.id} item={item} />
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
    </>
  );
}
