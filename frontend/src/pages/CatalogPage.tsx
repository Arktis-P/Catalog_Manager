import { useCallback, useEffect, useMemo, useState } from "react";
import { api, waitForBackend } from "../api/client";
import { useReviewRegenerateJobs } from "../context/ReviewRegenerateContext";
import type { CatalogItem, GlobalCatalogItem } from "../types";
import { CatalogCard } from "../components/CatalogCard";

const GLOBAL_PAGE_SIZE = 48;

export function CatalogPage() {
  const [error, setError] = useState<string | null>(null);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const [globalItems, setGlobalItems] = useState<GlobalCatalogItem[]>([]);
  const [globalTotal, setGlobalTotal] = useState(0);
  const [globalLoading, setGlobalLoading] = useState(true);
  const [globalLoadingMore, setGlobalLoadingMore] = useState(false);
  const {
    jobs,
    enqueueRegenerateGlobal,
    isCharacterRegenerating,
    lastCompletedJob,
    clearLastCompletedJob,
  } = useReviewRegenerateJobs();

  const activeRegenerateJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running"),
    [jobs],
  );

  const [showHiddenRatings, setShowHiddenRatings] = useState(false);
  const [alternativeFilter, setAlternativeFilter] = useState<"" | "true" | "false">("");
  const [search, setSearch] = useState("");
  const [gender, setGender] = useState("");
  const [rating, setRating] = useState<number | undefined>(undefined);

  const globalListFilters = useMemo(
    () => ({
      rating,
      gender: gender || undefined,
      search: search || undefined,
      include_hidden_ratings: showHiddenRatings || undefined,
      has_alternative: alternativeFilter === "" ? undefined : alternativeFilter === "true",
    }),
    [rating, gender, search, showHiddenRatings, alternativeFilter],
  );

  const loadGlobalInitial = useCallback(async () => {
    setGlobalLoading(true);
    setError(null);
    try {
      await waitForBackend();
      const response = await api.listGlobalCatalog({ ...globalListFilters, skip: 0, limit: GLOBAL_PAGE_SIZE });
      setGlobalItems(response.items);
      setGlobalTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load character-list catalog");
    } finally {
      setGlobalLoading(false);
    }
  }, [globalListFilters]);

  const loadMoreGlobal = useCallback(async () => {
    if (globalLoading || globalLoadingMore || globalItems.length >= globalTotal) {
      return;
    }
    setGlobalLoadingMore(true);
    try {
      const response = await api.listGlobalCatalog({
        ...globalListFilters,
        skip: globalItems.length,
        limit: GLOBAL_PAGE_SIZE,
      });
      setGlobalItems((current) => {
        const existing = new Set(current.map((entry) => entry.id));
        const appended = response.items.filter((entry) => !existing.has(entry.id));
        return [...current, ...appended];
      });
      setGlobalTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load more character-list catalog items");
    } finally {
      setGlobalLoadingMore(false);
    }
  }, [globalItems.length, globalListFilters, globalLoading, globalLoadingMore, globalTotal]);

  useEffect(() => {
    void loadGlobalInitial();
  }, [loadGlobalInitial]);

  const handleRegenerateGlobal = async (item: GlobalCatalogItem) => {
    const prompt = item.final_prompt || item.generation_prompt;
    if (!prompt?.trim()) {
      setError("재생성할 프롬프트가 없습니다.");
      return;
    }
    if (isCharacterRegenerating(item.id, "global")) {
      setExportMessage(`${item.character_tag} 재생성이 이미 진행 중입니다.`);
      return;
    }
    setError(null);
    try {
      const job = await enqueueRegenerateGlobal(item.id, {
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
    if (lastCompletedJob.scope !== "global") {
      return;
    }
    setExportMessage(
      `${lastCompletedJob.character_tag} 이미지 ${lastCompletedJob.result.images.length}장 재생성 완료`,
    );
    void loadGlobalInitial();
    clearLastCompletedJob();
  }, [clearLastCompletedJob, lastCompletedJob, loadGlobalInitial]);

  return (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-title">Catalog Viewer</h1>
          <p className="page-description">
            '리뷰 - 캐릭터 목록' 탭에서 검수된 캐릭터를 탐색하고 관리합니다.
          </p>
        </div>
        <div className="card-actions">
          <button
            className={`btn${showHiddenRatings ? " btn-primary" : ""}`}
            type="button"
            onClick={() => setShowHiddenRatings((current) => !current)}
          >
            {showHiddenRatings ? "레이팅 -1/0 숨기기" : "레이팅 -1/0 표시"}
          </button>
          <button className="btn" type="button" onClick={() => void loadGlobalInitial()}>
            Refresh
          </button>
        </div>
      </div>

      <section className="panel">
        <div className="page-header" style={{ marginBottom: 8 }}>
          <div>
            <h2 className="catalog-section-title">캐릭터 목록 리뷰 결과</h2>
            <p className="catalog-card-subtitle">
              '리뷰 - 캐릭터 목록' 탭에서 완료한 항목입니다 ({globalTotal.toLocaleString()}개).
            </p>
          </div>
          <div className="toolbar catalog-toolbar" style={{ marginBottom: 0 }}>
            <div className="field">
              <label htmlFor="search">Search</label>
              <input
                id="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="character / series"
              />
            </div>
            <div className="field">
              <label htmlFor="gender">Gender</label>
              <select id="gender" value={gender} onChange={(event) => setGender(event.target.value)}>
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
                value={rating === undefined ? "" : String(rating)}
                onChange={(event) => {
                  const value = event.target.value;
                  setRating(value === "" ? undefined : Number(value));
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
              <label htmlFor="alternative-filter">Alternative</label>
              <select
                id="alternative-filter"
                value={alternativeFilter}
                onChange={(event) => setAlternativeFilter(event.target.value as "" | "true" | "false")}
              >
                <option value="">All</option>
                <option value="true">Alternative만 표시</option>
                <option value="false">Alternative 숨기기</option>
              </select>
            </div>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {exportMessage ? <div className="success-banner">{exportMessage}</div> : null}
        {activeRegenerateJobs.length > 0 ? (
          <div className="catalog-card-subtitle">
            재생성 {activeRegenerateJobs.length}건 진행 중...
          </div>
        ) : null}

        {globalLoading && globalItems.length === 0 ? (
          <div className="empty-state">Loading...</div>
        ) : globalItems.length === 0 ? (
          <div className="empty-state">캐릭터 목록에서 완료된 리뷰 항목이 없습니다.</div>
        ) : (
          <>
            <div className="catalog-grid">
              {globalItems.map((item) => (
                <CatalogCard
                  key={`global-${item.id}`}
                  item={item as CatalogItem}
                  isGlobal
                  onRegenerate={(entry) => void handleRegenerateGlobal(entry as GlobalCatalogItem)}
                />
              ))}
            </div>
            {globalItems.length < globalTotal ? (
              <div className="pagination-bar">
                <span className="catalog-card-subtitle">
                  {globalItems.length.toLocaleString()} / {globalTotal.toLocaleString()} loaded
                </span>
                <button
                  className="btn btn-small"
                  type="button"
                  disabled={globalLoadingMore}
                  onClick={() => void loadMoreGlobal()}
                >
                  {globalLoadingMore ? "Loading..." : "Load more"}
                </button>
              </div>
            ) : null}
          </>
        )}
      </section>
    </>
  );
}
