import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useCharacterCatalogJobs } from "../context/CharacterCatalogJobContext";
import type { GlobalCharacter } from "../types";
import { collectStatusBadgeClass, collectStatusLabel } from "../utils/characterCatalogStatus";

const PAGE_SIZE_OPTIONS = [50, 100, 200];
const GENDER_OPTIONS = ["1girl", "1boy", "no_humans"];
const STATUS_OPTIONS = ["uncollected", "collecting", "completed", "partial", "failed", "needs_review"];

function formatDate(value: string | null): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function displayValue(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function CharacterDetailModal({ character, onClose }: { character: GlobalCharacter; onClose: () => void }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal modal-wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header-row">
          <span className="modal-title">{character.display_name || character.character_tag}</span>
          <button className="btn btn-small" type="button" onClick={onClose}>닫기</button>
        </div>
        <div className="modal-body-scroll">
          <table className="data-table">
            <tbody>
              <tr><td>character tag</td><td>{character.character_tag}</td></tr>
              <tr><td>post count</td><td>{character.post_count.toLocaleString()}</td></tr>
              <tr>
                <td>통합 상태</td>
                <td><span className={collectStatusBadgeClass(character.collect_status)}>{collectStatusLabel(character.collect_status)}</span></td>
              </tr>
              <tr>
                <td>외형</td>
                <td>
                  <span className={collectStatusBadgeClass(character.appearance_status)}>{collectStatusLabel(character.appearance_status)}</span>
                  {" · "}머리색: {displayValue(character.hair_color)} · 형태: {displayValue(character.hair_shape)} ·
                  {" "}멀티컬러: {displayValue(character.multi_color_hair)} · 눈색: {displayValue(character.eye_color)} ·
                  {" "}특징: {displayValue(character.feature_tags)}
                </td>
              </tr>
              <tr>
                <td>성별</td>
                <td>
                  <span className={collectStatusBadgeClass(character.gender_status)}>{collectStatusLabel(character.gender_status)}</span>
                  {" · "}{displayValue(character.gender)}
                </td>
              </tr>
              <tr>
                <td>관련 시리즈</td>
                <td>
                  <span className={collectStatusBadgeClass(character.series_status)}>{collectStatusLabel(character.series_status)}</span>
                  <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                    {character.series_links.length === 0 ? <li>-</li> : null}
                    {character.series_links.map((link) => (
                      <li key={link.copyright_tag}>
                        {link.is_primary ? "★ " : ""}
                        {link.series_tag ?? link.copyright_tag}
                        {link.is_user_edited ? " (수동 수정됨)" : ""}
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
              <tr><td>마지막 수집</td><td>{formatDate(character.last_collected_at)}</td></tr>
              <tr><td>재시도 횟수</td><td>{character.retry_count}</td></tr>
              {character.error_message ? (
                <tr><td>오류</td><td className="error-banner">{character.error_message}</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export function CharactersPage() {
  const { jobs, startListJob, startTagsJob, retryFailed, cancelJob, pauseJob, resumeJob, isJobActive, lastError, clearLastError } =
    useCharacterCatalogJobs();

  const [items, setItems] = useState<GlobalCharacter[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortBy, setSortBy] = useState("post_count");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [pageSize, setPageSize] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [viewingCharacter, setViewingCharacter] = useState<GlobalCharacter | null>(null);
  const [minPostCountInput, setMinPostCountInput] = useState("500");

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setCurrentPage(1);
  }, [search, genderFilter, statusFilter, pageSize, sortBy, sortOrder]);

  const loadCharacters = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listGlobalCharacters({
        search: search || undefined,
        gender: genderFilter || undefined,
        collect_status: statusFilter || undefined,
        sort_by: sortBy,
        sort_order: sortOrder,
        skip: (currentPage - 1) * pageSize,
        limit: pageSize,
      });
      setItems(response.items);
      setTotal(response.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load characters");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadCharacters();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, genderFilter, statusFilter, sortBy, sortOrder, currentPage, pageSize]);

  // 목록/통합 수집 작업이 끝나면 목록을 자동으로 새로고침
  const listJob = useMemo(() => jobs.find((j) => j.job_type === "character_catalog_list"), [jobs]);
  const tagsJob = useMemo(() => jobs.find((j) => j.job_type === "character_catalog_tags"), [jobs]);
  useEffect(() => {
    if (listJob?.status === "completed" || tagsJob?.status === "completed") {
      void loadCharacters();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listJob?.status, tagsJob?.status]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  const toggleSelection = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllOnPage = () => {
    setSelectedIds((current) => {
      const allSelected = items.every((item) => current.has(item.id));
      const next = new Set(current);
      for (const item of items) {
        if (allSelected) next.delete(item.id);
        else next.add(item.id);
      }
      return next;
    });
  };

  const handleStartListCollect = async () => {
    const minPostCount = Math.max(0, parseInt(minPostCountInput, 10) || 0);
    await startListJob(minPostCount, false);
  };

  const handleCollectSelected = async () => {
    if (selectedIds.size === 0) return;
    await startTagsJob([...selectedIds]);
  };

  const handleRetryFailed = async () => {
    await retryFailed();
  };

  const listJobActive = isJobActive("character_catalog_list");
  const tagsJobActive = isJobActive("character_catalog_tags");

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Characters</h1>
          <p className="page-description">
            Danbooru character 카테고리 태그 전체를 포스트 수 기준으로 수집하고, 외형·성별·시리즈 태그를 통합 수집합니다.
          </p>
        </div>
      </div>

      {lastError ? (
        <div className="error-banner">
          {lastError}
          <button className="btn btn-small" type="button" onClick={clearLastError}>닫기</button>
        </div>
      ) : null}

      <section className="panel">
        <div className="card-actions" style={{ alignItems: "center", flexWrap: "wrap", gap: 12 }}>
          <label className="series-toolbar-label" htmlFor="min-post-count">최소 포스트 수</label>
          <input
            id="min-post-count"
            style={{ width: 100 }}
            type="number"
            min={0}
            value={minPostCountInput}
            onChange={(e) => setMinPostCountInput(e.target.value)}
          />
          <button className="btn btn-primary" type="button" disabled={listJobActive} onClick={() => void handleStartListCollect()}>
            전체 캐릭터 목록 수집
          </button>
          <button className="btn" type="button" disabled={selectedIds.size === 0 || tagsJobActive} onClick={() => void handleCollectSelected()}>
            선택 캐릭터 통합 태그 수집 ({selectedIds.size})
          </button>
          <button className="btn" type="button" disabled={tagsJobActive} onClick={() => void handleRetryFailed()}>
            실패/부분완료 재시도
          </button>
        </div>

        {listJob && (listJob.status === "running" || listJob.status === "paused" || listJob.status === "queued") ? (
          <div className="pipeline-progress-row" style={{ marginTop: 12 }}>
            <span className="pipeline-progress-label">목록 수집: {listJob.message}</span>
            <div className="card-actions">
              {listJob.status === "running" ? (
                <button className="btn btn-small" type="button" onClick={() => void pauseJob(listJob.job_id)}>일시정지</button>
              ) : null}
              {listJob.status === "paused" ? (
                <button className="btn btn-small" type="button" onClick={() => void resumeJob(listJob.job_id)}>재개</button>
              ) : null}
              {listJob.status === "queued" || listJob.status === "paused" ? (
                <button className="btn btn-small btn-danger" type="button" onClick={() => void cancelJob(listJob.job_id)}>취소</button>
              ) : null}
            </div>
          </div>
        ) : null}

        {tagsJob && (tagsJob.status === "running" || tagsJob.status === "paused" || tagsJob.status === "queued") ? (
          <div className="pipeline-progress-row" style={{ marginTop: 12 }}>
            <span className="pipeline-progress-label">
              통합 태그 수집: {tagsJob.current}/{tagsJob.total} · 성공 {tagsJob.success_count} · 부분 {tagsJob.partial_count} · 실패 {tagsJob.failed_count}
              {tagsJob.current_character_tag ? ` · 현재: ${tagsJob.current_character_tag}` : ""}
            </span>
            <div className="card-actions">
              {tagsJob.status === "running" ? (
                <button className="btn btn-small" type="button" onClick={() => void pauseJob(tagsJob.job_id)}>일시정지</button>
              ) : null}
              {tagsJob.status === "paused" ? (
                <button className="btn btn-small" type="button" onClick={() => void resumeJob(tagsJob.job_id)}>재개</button>
              ) : null}
              {tagsJob.status === "queued" || tagsJob.status === "paused" ? (
                <button className="btn btn-small btn-danger" type="button" onClick={() => void cancelJob(tagsJob.job_id)}>취소</button>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel series-list-panel">
        <div className="series-sticky-toolbar">
          <div className="series-toolbar-search">
            <span className="series-toolbar-label">Search</span>
            <div className="search-input-row">
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="character tag / display name / 외형"
              />
              {searchInput ? (
                <button className="btn btn-small search-input-clear" type="button" onClick={() => setSearchInput("")}>✕</button>
              ) : null}
            </div>
          </div>
          <div className="series-toolbar-filters">
            <label className="series-toolbar-label" htmlFor="gender-filter">Gender</label>
            <select id="gender-filter" value={genderFilter} onChange={(e) => setGenderFilter(e.target.value)}>
              <option value="">All</option>
              {GENDER_OPTIONS.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
            <label className="series-toolbar-label" htmlFor="status-filter">Status</label>
            <select id="status-filter" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="">All</option>
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{collectStatusLabel(s)}</option>)}
            </select>
            <label className="series-toolbar-label" htmlFor="sort-by">Sort</label>
            <select id="sort-by" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              <option value="post_count">post count</option>
              <option value="display_name">name</option>
              <option value="last_collected_at">last collected</option>
              <option value="collect_status">status</option>
            </select>
            <select value={sortOrder} onChange={(e) => setSortOrder(e.target.value as "asc" | "desc")}>
              <option value="desc">desc</option>
              <option value="asc">asc</option>
            </select>
            <label className="series-toolbar-label" htmlFor="page-size">Show</label>
            <select id="page-size" value={String(pageSize)} onChange={(e) => setPageSize(Number(e.target.value))}>
              {PAGE_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </div>
          <div className="series-toolbar-refresh">
            <button className="btn" type="button" onClick={() => void loadCharacters()}>Refresh</button>
          </div>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {loading ? <div className="empty-state">Loading characters...</div> : null}

        {!loading ? (
          <>
            <div className="catalog-card-subtitle" style={{ marginBottom: 12 }}>
              표시: {items.length.toLocaleString()} / 전체 {total.toLocaleString()}개
            </div>
            {total > pageSize ? (
              <div className="series-pagination">
                <span className="series-pagination-info">
                  {((currentPage - 1) * pageSize + 1).toLocaleString()}–{Math.min(currentPage * pageSize, total).toLocaleString()} / {total.toLocaleString()}개
                </span>
                <div className="series-pagination-controls">
                  <button className="btn btn-small" type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>«</button>
                  <button className="btn btn-small" type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage((p) => p - 1)}>‹</button>
                  <span className="series-pagination-page-total">{currentPage} / {pageCount}</span>
                  <button className="btn btn-small" type="button" disabled={currentPage >= pageCount} onClick={() => setCurrentPage((p) => p + 1)}>›</button>
                  <button className="btn btn-small" type="button" disabled={currentPage >= pageCount} onClick={() => setCurrentPage(pageCount)}>»</button>
                </div>
              </div>
            ) : null}

            <div className="series-table-scroll">
              <table className="data-table series-table">
                <thead>
                  <tr>
                    <th className="col-checkbox">
                      <input
                        type="checkbox"
                        checked={items.length > 0 && items.every((item) => selectedIds.has(item.id))}
                        onChange={toggleAllOnPage}
                      />
                    </th>
                    <th>Character</th>
                    <th className="col-count">Post count</th>
                    <th className="col-status">통합 상태</th>
                    <th>대표 시리즈</th>
                    <th className="col-count">관련 시리즈</th>
                    <th>마지막 수집</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((character) => (
                    <tr key={character.id}>
                      <td className="col-checkbox">
                        <input type="checkbox" checked={selectedIds.has(character.id)} onChange={() => toggleSelection(character.id)} />
                      </td>
                      <td className="cell-ellipsis">
                        <button className="link-button" type="button" onClick={() => setViewingCharacter(character)}>
                          {character.display_name || character.character_tag}
                        </button>
                        <div className="catalog-card-subtitle">{character.character_tag}</div>
                      </td>
                      <td className="col-count">{character.post_count.toLocaleString()}</td>
                      <td className="col-status">
                        <span className={collectStatusBadgeClass(character.collect_status)}>
                          {collectStatusLabel(character.collect_status)}
                        </span>
                      </td>
                      <td className="cell-ellipsis">{character.primary_series_tag ?? "-"}</td>
                      <td className="col-count">{character.related_series_count}</td>
                      <td>{formatDate(character.last_collected_at)}</td>
                    </tr>
                  ))}
                  {items.length === 0 ? (
                    <tr><td colSpan={7} className="empty-state">캐릭터가 없습니다. 먼저 목록 수집을 실행하세요.</td></tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
      </section>

      {viewingCharacter ? (
        <CharacterDetailModal character={viewingCharacter} onClose={() => setViewingCharacter(null)} />
      ) : null}
    </div>
  );
}
