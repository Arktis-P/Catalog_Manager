import { FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { RunningJobCard } from "../components/CollectProgressPanel";
import { SeriesCharactersModal } from "../components/SeriesCharactersModal";
import { isSeriesMergeEligible, SeriesMergeModal } from "../components/SeriesMergeModal";
import { useCollectJobs } from "../context/CollectJobContext";
import type { DanbooruStatus, PipelineStatus, Series, SeriesCreatePayload } from "../types";
import { downloadTextFile } from "../utils/download";
import { danbooruSeriesWikiUrl } from "../utils/danbooruLinks";
import { resolveSeriesStatus, seriesStatusBadgeClass } from "../utils/seriesStatus";

type ModalMode = "create" | "edit";

function isSeriesSelectable(series: Series): boolean {
  return !series.is_merged_child;
}

function sortSeriesByPriority(seriesList: Series[]): Series[] {
  return [...seriesList].sort(
    (left, right) =>
      left.priority - right.priority || right.post_count - left.post_count || left.id - right.id,
  );
}

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
    startCollectMany,
    startAppearanceExtract,
    isProcessingSeries,
    isCollectingSeries,
    isExtractingAppearanceSeries,
    lastCompletedJob,
    clearLastCompletedJob,
    jobs: collectJobs,
    cancelJob,
  } = useCollectJobs();
  const [items, setItems] = useState<Series[]>([]);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [searchInput, setSearchInput] = useState("");
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
  const [selectedSeriesIds, setSelectedSeriesIds] = useState<Set<number>>(() => new Set());
  const [expandedParentIds, setExpandedParentIds] = useState<Set<number>>(() => new Set());
  const [exportingCharacters, setExportingCharacters] = useState(false);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [pageSize, setPageSize] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [total, setTotal] = useState(0);

  const pipelineRunningJobs = useMemo(
    () => collectJobs.filter((j) => j.status === "running"),
    [collectJobs],
  );
  const pipelineQueuedJobs = useMemo(
    () => collectJobs.filter((j) => j.status === "queued"),
    [collectJobs],
  );

  const mergeEligibleItems = useMemo(
    () => items.filter((series) => isSeriesMergeEligible(series)),
    [items],
  );

  const selectableItems = useMemo(() => items.filter((series) => isSeriesSelectable(series)), [items]);

  const selectedCollectTargets = useMemo(
    () => sortSeriesByPriority(items.filter((item) => selectedSeriesIds.has(item.id))),
    [items, selectedSeriesIds],
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

  const autoExpandedRef = useRef("");
  const prevSearchRef = useRef("");
  const stickyToolbarRef = useRef<HTMLDivElement>(null);
  const preSearchPageRef = useRef(1);

  const loadSeries = async (page = currentPage, size = pageSize) => {
    setLoading(true);
    setError(null);
    try {
      const [seriesResponse, statusList] = await Promise.all([
        api.listSeries({
          search: search || undefined,
          status: statusFilter || undefined,
          sort_by: "post_count",
          sort_order: "desc",
          skip: (page - 1) * size,
          limit: size,
          hierarchical: true,
        }),
        api.getSeriesStatuses(),
      ]);
      setItems(seriesResponse.items);
      setTotal(seriesResponse.total);
      setStatuses(statusList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load series");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (searchInput === search) return;
      const wasEmpty = !search.trim();
      const willBeEmpty = !searchInput.trim();
      if (wasEmpty && !willBeEmpty) {
        preSearchPageRef.current = currentPage;
      }
      setSearch(searchInput);
      setCurrentPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    void loadSeries();
  }, [search, statusFilter, currentPage, pageSize]);

  const resetSearch = () => {
    setSearchInput("");
    setSearch("");
    setCurrentPage(preSearchPageRef.current);
    autoExpandedRef.current = "";
    prevSearchRef.current = "";
    setExpandedParentIds(new Set());
  };

  useEffect(() => {
    const hadSearch = prevSearchRef.current.trim().length > 0;
    const hasSearch = search.trim().length > 0;
    prevSearchRef.current = search;

    if (!hasSearch) {
      autoExpandedRef.current = "";
      if (hadSearch) {
        setExpandedParentIds(new Set());
      }
      return;
    }
    const fingerprint = `${search}::${items.map((series) => series.id).join(",")}`;
    if (autoExpandedRef.current === fingerprint) {
      return;
    }
    const parentsToExpand = new Set<number>();
    for (const series of items) {
      if (series.is_merged_child && series.parent_series_id) {
        parentsToExpand.add(series.parent_series_id);
      }
    }
    if (parentsToExpand.size === 0) {
      autoExpandedRef.current = fingerprint;
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
    autoExpandedRef.current = fingerprint;
  }, [search, items]);

  useEffect(() => {
    void api
      .getDanbooruStatus()
      .then(setDanbooruStatus)
      .catch(() => setDanbooruStatus(null));
  }, []);

  useEffect(() => {
    void api
      .getPipelineStatus()
      .then(setPipelineStatus)
      .catch(() => null);
  }, []);

  useEffect(() => {
    if (!pipelineStatus || !["running", "stopping"].includes(pipelineStatus.status)) {
      return;
    }
    const timer = window.setInterval(() => {
      void api
        .getPipelineStatus()
        .then((status) => {
          setPipelineStatus(status);
          if (["completed", "stopped", "failed"].includes(status.status)) {
            void loadSeries();
          }
        })
        .catch(() => null);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pipelineStatus?.status]);

  useEffect(() => {
    if (!lastCompletedJob) {
      return;
    }
    const refreshCompletedSeries = async () => {
      try {
        const updated = await api.getSeries(lastCompletedJob.series_id);
        setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
        if (updated.parent_series_id !== null) {
          const parent = await api.getSeries(updated.parent_series_id);
          setItems((prev) => prev.map((item) => (item.id === parent.id ? parent : item)));
        }
      } catch {
        void loadSeries();
      } finally {
        clearLastCompletedJob();
      }
    };
    void refreshCompletedSeries();
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
      if (selectedSeriesIds.has(series.id) && selectedCollectTargets.length > 1) {
        await startCollectMany(selectedCollectTargets.map((item) => item.id));
        return;
      }
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

  const toggleSeriesSelection = (seriesId: number) => {
    setSelectedSeriesIds((current) => {
      const next = new Set(current);
      if (next.has(seriesId)) {
        next.delete(seriesId);
      } else {
        next.add(seriesId);
      }
      return next;
    });
  };

  const toggleAllSeriesSelection = () => {
    setSelectedSeriesIds((current) =>
      selectableItems.every((item) => current.has(item.id))
        ? new Set()
        : new Set(selectableItems.map((item) => item.id)),
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

  const selectAllChildren = (parentId: number) => {
    const childIds = items
      .filter((item) => item.is_merged_child && item.parent_series_id === parentId)
      .map((item) => item.id);
    setSelectedSeriesIds((current) => {
      const next = new Set(current);
      for (const id of childIds) next.add(id);
      return next;
    });
  };

  const openMergeModal = (series: Series) => {
    const selected = mergeEligibleItems.filter((item) => selectedSeriesIds.has(item.id));
    if (selectedSeriesIds.has(series.id) && selected.length > 1) {
      setMergingSeriesList(selected);
      return;
    }
    setMergingSeriesList([series]);
  };

  useLayoutEffect(() => {
    const appTop = document.querySelector(".app-top") as HTMLElement | null;
    if (!appTop) return;
    const update = () => {
      if (stickyToolbarRef.current) {
        stickyToolbarRef.current.style.top = `${appTop.offsetHeight}px`;
      }
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(appTop);
    return () => observer.disconnect();
  }, []);

  const [autoGenerate, setAutoGenerate] = useState(false);

  const handleStartPipeline = async () => {
    try {
      const status = await api.startPipeline(autoGenerate);
      setPipelineStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "파이프라인 시작 실패");
    }
  };

  const handleStopPipeline = async () => {
    try {
      const status = await api.stopPipeline();
      setPipelineStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : "파이프라인 중지 실패");
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

      <section className="pipeline-panel">
        <div className="pipeline-panel-header">
          <div className="pipeline-panel-title">
            전체 자동 수집
            {pipelineStatus?.status === "running" ? (
              <span className="pipeline-phase-badge">
                {pipelineStatus.phase === "collecting" && "Phase 1: 캐릭터 수집"}
                {pipelineStatus.phase === "collecting+extracting" && "Phase 1+2 병렬 진행 중"}
                {pipelineStatus.phase === "extracting" && "Phase 2: 외형 태그 추출"}
                {pipelineStatus.phase === "extracting+generating" && "Phase 2+3 병렬 진행 중"}
                {pipelineStatus.phase === "generating" && "Phase 3: 이미지 생성"}
              </span>
            ) : pipelineStatus?.status === "stopping" ? (
              <span className="pipeline-phase-badge pipeline-phase-badge-stopping">중지 중...</span>
            ) : null}
          </div>
          <div className="pipeline-panel-actions">
            {(!pipelineStatus || pipelineStatus.status === "idle") && (
              <>
                <label className="pipeline-auto-gen-toggle" title="추출 완료된 시리즈의 이미지 생성을 자동으로 시작합니다">
                  <input
                    type="checkbox"
                    checked={autoGenerate}
                    onChange={(e) => setAutoGenerate(e.target.checked)}
                  />
                  이미지 자동 생성
                </label>
                <button
                  className="btn btn-primary btn-small"
                  type="button"
                  disabled={danbooruStatus?.ready === false}
                  onClick={() => void handleStartPipeline()}
                >
                  전체 수집 시작
                </button>
              </>
            )}
            {pipelineStatus?.status === "running" && (
              <button className="btn btn-small btn-danger" type="button" onClick={() => void handleStopPipeline()}>
                중지
              </button>
            )}
            {pipelineStatus?.status === "stopping" && (
              <button className="btn btn-small" type="button" disabled>
                중지 중...
              </button>
            )}
            {pipelineStatus && ["completed", "stopped", "failed"].includes(pipelineStatus.status) && (
              <>
                <button
                  className="btn btn-primary btn-small"
                  type="button"
                  disabled={danbooruStatus?.ready === false}
                  onClick={() => void handleStartPipeline()}
                >
                  다시 시작
                </button>
                <button
                  className="btn btn-small"
                  type="button"
                  onClick={() => setPipelineStatus({ ...pipelineStatus, status: "idle" })}
                >
                  닫기
                </button>
              </>
            )}
          </div>
        </div>

        {pipelineStatus && pipelineStatus.status !== "idle" && (
          <div className="pipeline-panel-body">
            {(pipelineStatus.status === "running" || pipelineStatus.status === "stopping") && (
              <>
                {/* ── 전체 진행률 ── */}
                <div className="pipeline-overall-section">
                  <div className="pipeline-section-label">전체 진행률</div>

                  {/* Phase 1: 캐릭터 수집 */}
                  <div className="pipeline-progress-row">
                    <span className="pipeline-progress-label">
                      Phase 1 · 캐릭터 수집
                      {(pipelineStatus.phase === "collecting+extracting") && (
                        <span className="pipeline-phase-parallel"> (병렬)</span>
                      )}
                    </span>
                    <div className="pipeline-progress-bar-wrap">
                      <div
                        className="pipeline-progress-bar"
                        style={{
                          width:
                            pipelineStatus.collect_total > 0
                              ? `${Math.min(100, ((pipelineStatus.collect_done + pipelineStatus.collect_failed) / pipelineStatus.collect_total) * 100)}%`
                              : pipelineStatus.phase?.startsWith("collecting") ? "0%" : "100%",
                        }}
                      />
                    </div>
                    <span className="pipeline-progress-count">
                      {pipelineStatus.collect_total > 0
                        ? `${(pipelineStatus.collect_done + pipelineStatus.collect_failed).toLocaleString()} / ${pipelineStatus.collect_total.toLocaleString()}`
                        : "대기 중"}
                    </span>
                  </div>

                  {/* Phase 2: 외형 태그 추출 */}
                  <div className="pipeline-progress-row">
                    <span className="pipeline-progress-label">
                      Phase 2 · 외형 태그 추출
                      {(pipelineStatus.phase === "collecting+extracting" || pipelineStatus.phase === "extracting+generating") && (
                        <span className="pipeline-phase-parallel"> (병렬)</span>
                      )}
                    </span>
                    <div className="pipeline-progress-bar-wrap">
                      <div
                        className="pipeline-progress-bar"
                        style={{
                          width:
                            pipelineStatus.extract_total > 0
                              ? `${Math.min(100, ((pipelineStatus.extract_done + pipelineStatus.extract_failed) / pipelineStatus.extract_total) * 100)}%`
                              : "0%",
                        }}
                      />
                    </div>
                    <span className="pipeline-progress-count">
                      {pipelineStatus.extract_total > 0
                        ? `${(pipelineStatus.extract_done + pipelineStatus.extract_failed).toLocaleString()} / ${pipelineStatus.extract_total.toLocaleString()}`
                        : "대기 중"}
                    </span>
                  </div>

                  {/* Phase 3: 이미지 생성 (auto_generate 활성화 시) */}
                  {pipelineStatus.auto_generate && (
                    <div className="pipeline-progress-row">
                      <span className="pipeline-progress-label">
                        Phase 3 · 이미지 생성
                        {pipelineStatus.phase === "extracting+generating" && (
                          <span className="pipeline-phase-parallel"> (병렬)</span>
                        )}
                      </span>
                      <div className="pipeline-progress-bar-wrap">
                        <div
                          className="pipeline-progress-bar pipeline-progress-bar-generate"
                          style={{
                            width:
                              pipelineStatus.generate_total > 0
                                ? `${Math.min(100, ((pipelineStatus.generate_done + pipelineStatus.generate_failed) / pipelineStatus.generate_total) * 100)}%`
                                : "0%",
                          }}
                        />
                      </div>
                      <span className="pipeline-progress-count">
                        {pipelineStatus.generate_total > 0
                          ? `${(pipelineStatus.generate_done + pipelineStatus.generate_failed).toLocaleString()} / ${pipelineStatus.generate_total.toLocaleString()}`
                          : "대기 중"}
                      </span>
                    </div>
                  )}
                </div>

                {/* ── 현재 작업 중인 개별 카드 ── */}
                {pipelineRunningJobs.length > 0 ? (
                  <div className="pipeline-active-section">
                    <div className="pipeline-section-label">
                      현재 작업 중
                      <span className="pipeline-section-count">{pipelineRunningJobs.length}개</span>
                    </div>
                    <div className="pipeline-active-jobs">
                      {pipelineRunningJobs.map((job) => (
                        <RunningJobCard
                          key={job.job_id}
                          job={job}
                          onCancel={() => void cancelJob(job.job_id)}
                        />
                      ))}
                    </div>
                  </div>
                ) : pipelineStatus.current_series_tag ? (
                  /* 폴백: CollectJobContext 아직 미수신 시 pipelineStatus 정보 표시 */
                  <div className="pipeline-active-section">
                    <div className="pipeline-section-label">현재 작업 중</div>
                    <div className="pipeline-live-ticker">
                      <span className="job-running-indicator" aria-hidden="true" />
                      <strong className="pipeline-live-series">{pipelineStatus.current_series_tag}</strong>
                      {pipelineStatus.current_job_message ? (
                        <span className="pipeline-live-msg">{pipelineStatus.current_job_message}</span>
                      ) : null}
                    </div>
                  </div>
                ) : (
                  /* 파이프라인 시작 직후 — 작업 배분 중 */
                  <div className="pipeline-active-section">
                    <div className="pipeline-section-label">현재 작업 중</div>
                    <div className="pipeline-live-ticker pipeline-live-preparing">
                      <span className="job-running-indicator" aria-hidden="true" />
                      <span className="pipeline-live-msg">작업 배분 중... (잠시 후 표시됩니다)</span>
                    </div>
                  </div>
                )}

                {/* ── 대기 중 요약 ── */}
                {pipelineQueuedJobs.length > 0 && (
                  <div className="pipeline-queued-section">
                    <span className="pipeline-queued-label">
                      대기 중
                      <span className="pipeline-section-count">{pipelineQueuedJobs.length}개</span>
                    </span>
                    <span className="pipeline-queued-tags">
                      {pipelineQueuedJobs
                        .filter((j) => j.series_tag)
                        .slice(0, 6)
                        .map((j) => j.series_tag)
                        .join(" · ")}
                      {pipelineQueuedJobs.length > 6 ? ` +${pipelineQueuedJobs.length - 6}개` : ""}
                    </span>
                  </div>
                )}
              </>
            )}

            {["completed", "stopped", "failed"].includes(pipelineStatus.status) && (
              <div className="pipeline-summary">
                <span
                  className={`pipeline-summary-status ${
                    pipelineStatus.status === "completed"
                      ? "pipeline-summary-completed"
                      : pipelineStatus.status === "failed"
                        ? "pipeline-summary-failed"
                        : "pipeline-summary-stopped"
                  }`}
                >
                  {pipelineStatus.status === "completed" ? "완료" : pipelineStatus.status === "failed" ? "실패" : "중지됨"}
                </span>
                <span className="pipeline-summary-detail">
                  수집 {pipelineStatus.collect_done.toLocaleString()} / {pipelineStatus.collect_total.toLocaleString()}
                  {pipelineStatus.collect_failed > 0 ? ` (실패 ${pipelineStatus.collect_failed})` : ""}
                  {" · "}
                  외형 추출 {pipelineStatus.extract_done.toLocaleString()} / {pipelineStatus.extract_total.toLocaleString()}
                  {pipelineStatus.extract_failed > 0 ? ` (실패 ${pipelineStatus.extract_failed})` : ""}
                  {pipelineStatus.auto_generate && pipelineStatus.generate_total > 0 && (
                    <>
                      {" · "}
                      이미지 생성 {pipelineStatus.generate_done.toLocaleString()} / {pipelineStatus.generate_total.toLocaleString()}
                      {pipelineStatus.generate_failed > 0 ? ` (실패 ${pipelineStatus.generate_failed})` : ""}
                    </>
                  )}
                </span>
              </div>
            )}

            {pipelineStatus.errors.length > 0 && (
              <div className="pipeline-errors">
                {pipelineStatus.errors.slice(-3).map((err, i) => (
                  <div key={i} className="pipeline-error-line">
                    {err}
                  </div>
                ))}
                {pipelineStatus.errors.length > 3 && (
                  <div className="pipeline-error-line pipeline-error-more">
                    +{pipelineStatus.errors.length - 3}개 오류 더 있음
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      <section className="panel series-list-panel">
        <div className="series-sticky-toolbar" ref={stickyToolbarRef}>
          <div className="series-toolbar-search">
            <span className="series-toolbar-label">Search</span>
            <div className="search-input-row">
              <input
                id="series-search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="series tag / display name"
              />
              {searchInput ? (
                <button
                  className="btn btn-small search-input-clear"
                  type="button"
                  aria-label="검색 초기화"
                  title="검색 초기화"
                  onClick={resetSearch}
                >
                  ✕
                </button>
              ) : null}
            </div>
          </div>
          <div className="series-toolbar-filters">
            <label htmlFor="series-status" className="series-toolbar-label">Status</label>
            <select
              id="series-status"
              value={statusFilter}
              onChange={(event) => { setStatusFilter(event.target.value); setCurrentPage(1); }}
            >
              <option value="">All</option>
              {statuses.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <label htmlFor="import-replace" className="series-toolbar-label">Import</label>
            <select
              id="import-replace"
              value={String(importReplace)}
              onChange={(event) => setImportReplace(event.target.value === "true")}
            >
              <option value="false">Merge</option>
              <option value="true">Replace all</option>
            </select>
            <label htmlFor="series-page-size" className="series-toolbar-label">Show</label>
            <select
              id="series-page-size"
              value={String(pageSize)}
              onChange={(event) => { setPageSize(Number(event.target.value)); setCurrentPage(1); }}
            >
              <option value="50">50</option>
              <option value="100">100</option>
              <option value="200">200</option>
            </select>
          </div>
          <div className="series-toolbar-refresh">
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
              표시: {visibleItems.length.toLocaleString()} / 전체 {total.toLocaleString()}개
              {hiddenChildCount > 0 ? ` · 하위 시리즈 ${hiddenChildCount.toLocaleString()}개 숨김` : null}
            </div>
            {total > pageSize ? (
              <div className="series-pagination">
                <span className="series-pagination-info">
                  {((currentPage - 1) * pageSize + 1).toLocaleString()}–{Math.min(currentPage * pageSize, total).toLocaleString()} / {total.toLocaleString()}개
                </span>
                <div className="series-pagination-controls">
                  <button className="btn btn-small" type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>«</button>
                  <button className="btn btn-small" type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage((p) => p - 1)}>‹</button>
                  <span className="series-pagination-page">{currentPage} / {Math.ceil(total / pageSize)}</span>
                  <button className="btn btn-small" type="button" disabled={currentPage >= Math.ceil(total / pageSize)} onClick={() => setCurrentPage((p) => p + 1)}>›</button>
                  <button className="btn btn-small" type="button" disabled={currentPage >= Math.ceil(total / pageSize)} onClick={() => setCurrentPage(Math.ceil(total / pageSize))}>»</button>
                </div>
              </div>
            ) : null}
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
                      {selectableItems.length > 0 ? (
                        <input
                          type="checkbox"
                          aria-label="Select all series"
                          checked={
                            selectableItems.length > 0 &&
                            selectableItems.every((item) => selectedSeriesIds.has(item.id))
                          }
                          onChange={toggleAllSeriesSelection}
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
                        <input
                          type="checkbox"
                          aria-label={`Select ${series.series_tag}`}
                          checked={selectedSeriesIds.has(series.id)}
                          onChange={() => toggleSeriesSelection(series.id)}
                        />
                      </td>
                      <td className="col-series-tag cell-ellipsis" title={series.series_tag}>
                        <div className="series-tag-cell">
                          {!series.is_merged_child && series.child_count > 0 ? (
                            <>
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
                              {expandedParentIds.has(series.id) ? (
                                <button
                                  type="button"
                                  className="series-children-toggle"
                                  title="하위 시리즈 전체 선택"
                                  onClick={() => selectAllChildren(series.id)}
                                >
                                  <span aria-hidden="true">☑</span>
                                </button>
                              ) : null}
                            </>
                          ) : null}
                          <span className={series.is_merged_child ? "series-child-tag" : undefined}>
                            {series.is_merged_child ? `└ ${series.series_tag}` : series.series_tag}
                          </span>
                        </div>
                      </td>
                      <td className="col-display-name" title={series.display_name}>
                        <div className="series-display-name-cell">
                          <span className="series-display-name-text">{series.display_name}</span>
                          <a
                            href={danbooruSeriesWikiUrl(series.series_tag)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="series-wiki-btn"
                            title={`Danbooru wiki: ${series.series_tag}`}
                          >
                            W
                          </a>
                        </div>
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
                                className="btn btn-small btn-primary"
                                type="button"
                                disabled={isProcessingSeries(series.id) || danbooruStatus?.ready === false}
                                title={
                                  selectedSeriesIds.has(series.id) && selectedCollectTargets.length > 1
                                    ? `선택한 ${selectedCollectTargets.length}개 시리즈 수집 (priority 순)`
                                    : undefined
                                }
                                onClick={() => void handleCollectCharacters(series)}
                              >
                                {isCollectingSeries(series.id) ? "Collecting..." : "Collect"}
                              </button>
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
                                title={
                                  selectedSeriesIds.has(series.id) && selectedCollectTargets.length > 1
                                    ? `선택한 ${selectedCollectTargets.length}개 시리즈 수집 (priority 순)`
                                    : undefined
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
            {total > pageSize ? (
              <div className="series-pagination series-pagination-bottom">
                <span className="series-pagination-info">
                  {((currentPage - 1) * pageSize + 1).toLocaleString()}–{Math.min(currentPage * pageSize, total).toLocaleString()} / {total.toLocaleString()}개
                </span>
                <div className="series-pagination-controls">
                  <button className="btn btn-small" type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage(1)}>«</button>
                  <button className="btn btn-small" type="button" disabled={currentPage <= 1} onClick={() => setCurrentPage((p) => p - 1)}>‹</button>
                  <span className="series-pagination-page">{currentPage} / {Math.ceil(total / pageSize)}</span>
                  <button className="btn btn-small" type="button" disabled={currentPage >= Math.ceil(total / pageSize)} onClick={() => setCurrentPage((p) => p + 1)}>›</button>
                  <button className="btn btn-small" type="button" disabled={currentPage >= Math.ceil(total / pageSize)} onClick={() => setCurrentPage(Math.ceil(total / pageSize))}>»</button>
                </div>
              </div>
            ) : null}
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
            setSelectedSeriesIds(new Set());
            void loadSeries();
          }}
        />
      ) : null}
    </>
  );
}
