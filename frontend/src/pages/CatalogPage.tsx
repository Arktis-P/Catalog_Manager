import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CatalogFilters, CatalogItem, CatalogStats } from "../types";
import { CatalogCard } from "../components/CatalogCard";

const emptyStats: CatalogStats = {
  series_count: 0,
  character_count: 0,
  completed_count: 0,
  cover_image_count: 0,
};

export function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [stats, setStats] = useState<CatalogStats>(emptyStats);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [seriesOptions, setSeriesOptions] = useState<string[]>([]);
  const [filters, setFilters] = useState<CatalogFilters>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter((value) => value !== undefined && value !== "").length,
    [filters],
  );

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [catalog, catalogStats, catalogStatuses, seriesList] = await Promise.all([
        api.listCatalog(filters),
        api.getCatalogStats(),
        api.getCatalogStatuses(),
        api.listSeries({ sort_by: "post_count", sort_order: "desc", limit: 500 }),
      ]);
      setItems(catalog.items);
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
    void loadData();
  }, [filters]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Catalog Viewer</h1>
          <p className="page-description">
            수집/생성/검수 상태를 확인하고 작업 허브로 이동할 수 있는 메인 화면입니다.
          </p>
        </div>
        <button className="btn" type="button" onClick={() => void loadData()}>
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
          <div className="stat-value">{stats.character_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Completed</div>
          <div className="stat-value">{stats.completed_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Cover Images</div>
          <div className="stat-value">{stats.cover_image_count}</div>
        </div>
      </div>

      <section className="panel">
        <div className="toolbar">
          <div className="field">
            <label htmlFor="search">Search</label>
            <input
              id="search"
              value={filters.search ?? ""}
              onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
              placeholder="character / series"
            />
          </div>
          <div className="field">
            <label htmlFor="series">Series</label>
            <select
              id="series"
              value={filters.series_tag ?? ""}
              onChange={(event) =>
                setFilters((prev) => ({ ...prev, series_tag: event.target.value || undefined }))
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
                setFilters((prev) => ({ ...prev, status: event.target.value || undefined }))
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
                setFilters((prev) => ({
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
                setFilters((prev) => ({
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
            <button className="btn" type="button" onClick={() => setFilters({})}>
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
          <div className="catalog-grid">
            {items.map((item) => (
              <CatalogCard key={item.id} item={item} />
            ))}
          </div>
        ) : null}
      </section>
    </>
  );
}
