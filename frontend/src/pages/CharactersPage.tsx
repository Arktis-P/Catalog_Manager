import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { useCharacterCatalogJobs } from "../context/CharacterCatalogJobContext";
import { useGenerationJobs } from "../context/GenerationJobContext";
import type { GlobalCharacter } from "../types";
import { collectStatusBadgeClass, collectStatusLabel } from "../utils/characterCatalogStatus";
import { danbooruWikiUrl, openExternal } from "../utils/danbooruLinks";

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

// 관련도(빈도) 순으로 저장된 콤마 구분 태그 문자열에서 앞쪽 n개만 취한다.
function firstNTags(value: string | null | undefined, n: number): string | null {
  if (!value || !value.trim()) return null;
  const parts = value.split(",").map((part) => part.trim()).filter(Boolean);
  if (parts.length === 0) return null;
  return parts.slice(0, n).join(", ");
}

function MiniStatus({ label, status }: { label: string; status: string }) {
  return (
    <span
      className={`${collectStatusBadgeClass(status)} badge-compact`}
      title={`${label}: ${collectStatusLabel(status)}`}
    >
      {label}
    </span>
  );
}

function genderBadgeClass(gender: string | null | undefined): string {
  if (gender === "1boy") return "badge badge-gender-boy";
  if (gender === "1girl") return "badge badge-gender-girl";
  return "badge badge-gender-other";
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
              <tr>
                <td>이미지</td>
                <td>
                  {character.image_count > 0 ? `생성됨 (${character.image_count}장)` : "미생성"}
                  {" · "}
                  {character.has_cover_image ? "커버 선택됨" : "커버 미선택"}
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
  const { jobs, startListJob, startTagsJob, retryFailed, collectAllUncollected, isJobActive, lastError, clearLastError } =
    useCharacterCatalogJobs();
  const { startCharacterGeneration, isGeneratingCharacters } = useGenerationJobs();

  const [items, setItems] = useState<GlobalCharacter[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [imageFilter, setImageFilter] = useState<"" | "yes" | "no">("");
  const [coverFilter, setCoverFilter] = useState<"" | "yes" | "no">("");
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
  }, [search, genderFilter, statusFilter, imageFilter, coverFilter, pageSize, sortBy, sortOrder]);

  const loadCharacters = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.listGlobalCharacters({
        search: search || undefined,
        gender: genderFilter || undefined,
        collect_status: statusFilter || undefined,
        has_image: imageFilter ? imageFilter === "yes" : undefined,
        has_cover: coverFilter ? coverFilter === "yes" : undefined,
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
  }, [search, genderFilter, statusFilter, imageFilter, coverFilter, sortBy, sortOrder, currentPage, pageSize]);

  // 목록/통합 수집 작업이 끝나면 목록을 자동으로 새로고침 (진행 상태 자체는 GlobalTaskBar에 표시됨)
  // 여러 태그 수집 job이 동시에 진행될 수 있으므로, 완료된 job 집합이 바뀔 때마다 새로고침한다.
  const completedJobIds = useMemo(
    () => jobs.filter((j) => j.status === "completed").map((j) => j.job_id).join("|"),
    [jobs],
  );
  useEffect(() => {
    if (completedJobIds) {
      void loadCharacters();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [completedJobIds]);

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

  const handleCollectSingle = async (id: number) => {
    await startTagsJob([id]);
  };

  const handleRetryFailed = async () => {
    await retryFailed();
  };

  const handleCollectAllUncollected = async () => {
    await collectAllUncollected();
  };

  const handleGenerateSelected = async () => {
    if (selectedIds.size === 0) return;
    await startCharacterGeneration([...selectedIds]);
  };

  const handleGenerateSingle = async (id: number) => {
    await startCharacterGeneration([id]);
  };

  const handleGeneratePage = async () => {
    if (items.length === 0) return;
    const ids = items.map((item) => item.id);
    setSelectedIds(new Set(ids));
    await startCharacterGeneration(ids);
    setSelectedIds(new Set());
  };

  const listJobActive = isJobActive("character_catalog_list");

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Characters</h1>
          <p className="page-description">
            Danbooru character 카테고리 태그 전체를 포스트 수 기준으로 수집하고, 외형·성별·시리즈 태그를 통합 수집합니다.
            작업 진행 상태는 좌측 통합 작업 내역에서 확인할 수 있습니다.
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
          <button className="btn" type="button" disabled={selectedIds.size === 0} onClick={() => void handleCollectSelected()}>
            선택 캐릭터 통합 태그 수집 ({selectedIds.size})
          </button>
          <button className="btn" type="button" onClick={() => void handleRetryFailed()}>
            실패/부분완료 재시도
          </button>
          <button className="btn" type="button" onClick={() => void handleCollectAllUncollected()}>
            미수집 전체 태그 수집
          </button>
          <span className="series-toolbar-label" style={{ marginLeft: 12 }}>이미지 생성</span>
          <button className="btn" type="button" disabled={selectedIds.size === 0} onClick={() => void handleGenerateSelected()}>
            선택 캐릭터 이미지 생성 ({selectedIds.size})
          </button>
          <button className="btn" type="button" disabled={items.length === 0} onClick={() => void handleGeneratePage()}>
            현재 페이지 이미지 생성
          </button>
          {isGeneratingCharacters() ? (
            <span className="badge badge-info">캐릭터 목록 이미지 생성 진행/대기 중</span>
          ) : null}
        </div>
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
            <label className="series-toolbar-label" htmlFor="image-filter">이미지 생성</label>
            <select
              id="image-filter"
              value={imageFilter}
              onChange={(e) => setImageFilter(e.target.value as "" | "yes" | "no")}
            >
              <option value="">All</option>
              <option value="yes">생성됨</option>
              <option value="no">미생성</option>
            </select>
            <label className="series-toolbar-label" htmlFor="cover-filter">커버 선택</label>
            <select
              id="cover-filter"
              value={coverFilter}
              onChange={(e) => setCoverFilter(e.target.value as "" | "yes" | "no")}
            >
              <option value="">All</option>
              <option value="yes">선택됨</option>
              <option value="no">미선택</option>
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
              <table className="data-table series-table characters-table-compact">
                <thead>
                  <tr>
                    <th className="col-checkbox">
                      <input
                        type="checkbox"
                        checked={items.length > 0 && items.every((item) => selectedIds.has(item.id))}
                        onChange={toggleAllOnPage}
                      />
                    </th>
                    <th className="col-wiki"></th>
                    <th className="col-character-name">Character</th>
                    <th className="col-count">Post count</th>
                    <th className="col-character-status">통합 상태</th>
                    <th className="col-character-series">대표 시리즈</th>
                    <th className="col-appearance">머리색</th>
                    <th className="col-appearance">멀티컬러</th>
                    <th className="col-appearance">머리 모양</th>
                    <th className="col-appearance">눈색</th>
                    <th className="col-appearance">기타 외형</th>
                    <th className="col-gender">성별</th>
                    <th className="col-character-image">이미지</th>
                    <th className="col-row-action"></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((character) => (
                    <tr key={character.id}>
                      <td className="col-checkbox">
                        <input type="checkbox" checked={selectedIds.has(character.id)} onChange={() => toggleSelection(character.id)} />
                      </td>
                      <td className="col-wiki">
                        <button
                          type="button"
                          className="series-wiki-btn"
                          title={`Danbooru wiki: ${character.character_tag}`}
                          onClick={() => openExternal(danbooruWikiUrl(character.character_tag))}
                        >
                          W
                        </button>
                      </td>
                      <td className="col-character-name" title={`${character.display_name} (${character.character_tag})`}>
                        <button className="link-button" type="button" onClick={() => setViewingCharacter(character)}>
                          {character.display_name || character.character_tag}
                        </button>
                        {" "}
                        <span className="catalog-card-subtitle characters-tag-inline">{character.character_tag}</span>
                      </td>
                      <td className="col-count">{character.post_count.toLocaleString()}</td>
                      <td className="col-character-status">
                        <span className={collectStatusBadgeClass(character.collect_status)}>
                          {collectStatusLabel(character.collect_status)}
                        </span>
                        {" "}
                        <MiniStatus label="외형" status={character.appearance_status} />
                        {" "}
                        <MiniStatus label="성별" status={character.gender_status} />
                        {" "}
                        <MiniStatus label="시리즈" status={character.series_status} />
                      </td>
                      <td className="col-character-series" title={character.primary_series_tag ?? "-"}>
                        {character.primary_series_tag ?? "-"}
                      </td>
                      <td className="col-appearance" title={character.hair_color ?? ""}>
                        {firstNTags(character.hair_color, 2) ?? "-"}
                      </td>
                      <td className="col-appearance" title={character.multi_color_hair ?? ""}>
                        {firstNTags(character.multi_color_hair, 1) ?? "-"}
                      </td>
                      <td className="col-appearance" title={character.hair_shape ?? ""}>
                        {firstNTags(character.hair_shape, 1) ?? "-"}
                      </td>
                      <td className="col-appearance" title={character.eye_color ?? ""}>
                        {firstNTags(character.eye_color, 1) ?? "-"}
                      </td>
                      <td className="col-appearance" title={character.feature_tags ?? ""}>
                        {firstNTags(character.feature_tags, 1) ?? "-"}
                      </td>
                      <td className="col-gender">
                        {character.gender ? <span className={genderBadgeClass(character.gender)}>{character.gender}</span> : "-"}
                      </td>
                      <td className="col-character-image">
                        <span className={`badge ${character.image_count > 0 ? "badge-success" : "badge-muted"}`}>
                          {character.image_count > 0 ? `생성됨 (${character.image_count})` : "미생성"}
                        </span>
                        {" "}
                        <span className={`badge ${character.has_cover_image ? "badge-success" : "badge-muted"}`}>
                          {character.has_cover_image ? "커버 선택됨" : "커버 미선택"}
                        </span>
                      </td>
                      <td className="col-row-action">
                        <button
                          className="btn btn-small"
                          type="button"
                          onClick={() => void handleCollectSingle(character.id)}
                        >
                          태그 수집
                        </button>
                        {" "}
                        <button
                          className="btn btn-small"
                          type="button"
                          disabled={character.collect_status !== "completed"}
                          title={
                            character.collect_status !== "completed"
                              ? "특징 태그 수집이 완료되어야 이미지 생성이 가능합니다"
                              : undefined
                          }
                          onClick={() => void handleGenerateSingle(character.id)}
                        >
                          이미지 생성
                        </button>
                      </td>
                    </tr>
                  ))}
                  {items.length === 0 ? (
                    <tr><td colSpan={14} className="empty-state">캐릭터가 없습니다. 먼저 목록 수집을 실행하세요.</td></tr>
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
