import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { GenerationProgressPanel } from "../components/GenerationProgressPanel";
import { useGenerationJobs } from "../context/GenerationJobContext";
import type { GenerationCandidate, GenerationQueuePreview, NaiaStatus, Series } from "../types";

function pendingReviewImageUrl(imagePath: string | null | undefined): string | null {
  if (!imagePath) {
    return null;
  }
  const filename = imagePath.split(/[\\/]/).pop();
  return filename ? `/media/pending-review/${filename}` : null;
}

export function GenerationPage() {
  const { jobs, startGeneration, cancelJob, dismissJob, isGeneratingSeries } = useGenerationJobs();
  const [seriesList, setSeriesList] = useState<Series[]>([]);
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | "">("");
  const [candidates, setCandidates] = useState<GenerationCandidate[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [promptLevel, setPromptLevel] = useState(1);
  const [requireConfirmed, setRequireConfirmed] = useState(true);
  const [search, setSearch] = useState("");
  const [naiaStatus, setNaiaStatus] = useState<NaiaStatus | null>(null);
  const [queuePreview, setQueuePreview] = useState<GenerationQueuePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingCandidates, setLoadingCandidates] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeJob = useMemo(
    () =>
      jobs.find(
        (job) =>
          job.job_type === "image_generation" &&
          (job.status === "queued" || job.status === "running") &&
          (selectedSeriesId === "" || job.series_id === selectedSeriesId),
      ) ?? null,
    [jobs, selectedSeriesId],
  );

  const recentCompletedJobs = useMemo(
    () =>
      jobs
        .filter((job) => job.job_type === "image_generation")
        .slice(0, 5),
    [jobs],
  );

  useEffect(() => {
    void (async () => {
      setLoading(true);
      const errors: string[] = [];

      const seriesPromise = api
        .listSeries({ sort_by: "series_tag", sort_order: "asc", limit: 500 })
        .then((response) => setSeriesList(response.items))
        .catch((err) => {
          errors.push(err instanceof Error ? err.message : "시리즈 목록을 불러오지 못했습니다.");
        });

      const naiaPromise = api
        .getNaiaStatus()
        .then((response) => setNaiaStatus(response))
        .catch((err) => {
          errors.push(err instanceof Error ? err.message : "NAIA 상태를 확인하지 못했습니다.");
        });

      await Promise.all([seriesPromise, naiaPromise]);
      if (errors.length > 0) {
        setError(errors.join(" / "));
      }
      setLoading(false);
    })();
  }, []);

  useEffect(() => {
    if (!selectedSeriesId) {
      setCandidates([]);
      setSelectedIds(new Set());
      setQueuePreview(null);
      return;
    }

    void (async () => {
      setLoadingCandidates(true);
      setError(null);
      try {
        const response = await api.listGenerationCandidates(selectedSeriesId, {
          require_confirmed: requireConfirmed,
          search: search || undefined,
        });
        setCandidates(response.items);
        setSelectedIds(new Set(response.items.map((item) => item.id)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "캐릭터 목록을 불러오지 못했습니다.");
      } finally {
        setLoadingCandidates(false);
      }
    })();
  }, [selectedSeriesId, requireConfirmed, search]);

  const toggleCandidate = (id: number) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handlePreviewQueue = async () => {
    if (!selectedSeriesId) {
      return;
    }
    setPreviewing(true);
    setError(null);
    try {
      const preview = await api.previewGenerationQueue(selectedSeriesId, {
        character_ids: selectedIds.size > 0 ? Array.from(selectedIds) : null,
        prompt_level: promptLevel,
        require_confirmed: requireConfirmed,
      });
      setQueuePreview(preview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "큐 미리보기 실패");
    } finally {
      setPreviewing(false);
    }
  };

  const handleStart = async () => {
    if (!selectedSeriesId) {
      return;
    }
    setStarting(true);
    setError(null);
    try {
      await startGeneration(selectedSeriesId, {
        character_ids: selectedIds.size > 0 ? Array.from(selectedIds) : undefined,
        prompt_level: promptLevel,
        require_confirmed: requireConfirmed,
      });
      setQueuePreview(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "이미지 생성 시작 실패");
    } finally {
      setStarting(false);
    }
  };

  const selectedSeries = seriesList.find((series) => series.id === selectedSeriesId);

  return (
    <section className="generation-page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Generation</h1>
          <p className="page-description">
            시리즈별 generation_prompt를 NAIA 와일드카드로보내고, NAIA API로 이미지를 생성한 뒤
            검수 대기 폴더에 저장합니다.
          </p>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="generation-layout">
        <div className="panel generation-controls">
          <h2 className="section-title">NAIA 연결</h2>
          {naiaStatus ? (
            <div className="generation-status-grid">
              <div>
                <span className="field-label">상태</span>
                <div>
                  <span className={`badge ${naiaStatus.ready ? "badge-success" : "badge-warning"}`}>
                    {naiaStatus.ready ? "연결됨" : "미연결"}
                  </span>
                </div>
              </div>
              <div>
                <span className="field-label">API</span>
                <div className="mono-text">{naiaStatus.base_url}</div>
              </div>
              <div className="full-width">
                <span className="field-label">Portable 경로</span>
                <div className="mono-text">{naiaStatus.portable_dir}</div>
              </div>
              <div className="full-width">
                <span className="field-label">Wildcards</span>
                <div className="mono-text">{naiaStatus.wildcards_dir}</div>
              </div>
              {!naiaStatus.ready ? <p className="field-help">{naiaStatus.message}</p> : null}
            </div>
          ) : (
            <div className="empty-state">NAIA 상태 확인 중...</div>
          )}

          <h2 className="section-title">생성 대상</h2>
          <div className="form-grid">
            <div className="field full-width">
              <label htmlFor="generation-series">시리즈</label>
              <select
                id="generation-series"
                value={selectedSeriesId}
                onChange={(event) =>
                  setSelectedSeriesId(event.target.value ? Number(event.target.value) : "")
                }
                disabled={loading}
              >
                <option value="">시리즈 선택...</option>
                {seriesList.map((series) => (
                  <option key={series.id} value={series.id}>
                    {series.series_tag} ({series.character_count})
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="generation-level">Prompt Level</label>
              <select
                id="generation-level"
                value={promptLevel}
                onChange={(event) => setPromptLevel(Number(event.target.value))}
              >
                <option value={1}>Level 1 — generation_prompt</option>
                <option value={2}>Level 2 — 기본 캐릭터 코어</option>
                <option value={3}>Level 3 — 헤어/눈 형태 포함</option>
                <option value={4}>Level 4 — feature tags 포함</option>
                <option value={5}>Level 5 — artist/quality/배경 템플릿</option>
              </select>
            </div>

            <div className="field">
              <label htmlFor="generation-search">검색</label>
              <input
                id="generation-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="character tag"
                disabled={!selectedSeriesId}
              />
            </div>

            <div className="field full-width">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={requireConfirmed}
                  onChange={(event) => setRequireConfirmed(event.target.checked)}
                />
                외형 태그 확정된 캐릭터만 포함
              </label>
            </div>
          </div>

          <div className="modal-actions">
            <button
              className="btn"
              type="button"
              disabled={!selectedSeriesId || previewing || loadingCandidates}
              onClick={() => void handlePreviewQueue()}
            >
              {previewing ? "미리보기 중..." : "큐 미리보기"}
            </button>
            <button
              className="btn btn-primary"
              type="button"
              disabled={
                !selectedSeriesId ||
                !naiaStatus?.ready ||
                starting ||
                isGeneratingSeries(Number(selectedSeriesId)) ||
                candidates.length === 0
              }
              onClick={() => void handleStart()}
            >
              {starting ? "시작 중..." : "이미지 생성 시작"}
            </button>
          </div>
        </div>

        <div className="panel generation-candidates">
          <div className="section-header-row">
            <h2 className="section-title">
              캐릭터 목록
              {selectedSeries ? ` · ${selectedSeries.series_tag}` : ""}
            </h2>
            {candidates.length > 0 ? (
              <button
                className="btn btn-small"
                type="button"
                onClick={() =>
                  setSelectedIds((current) =>
                    current.size === candidates.length
                      ? new Set()
                      : new Set(candidates.map((item) => item.id)),
                  )
                }
              >
                {selectedIds.size === candidates.length ? "전체 해제" : "전체 선택"}
              </button>
            ) : null}
          </div>

          {loadingCandidates ? <div className="empty-state">캐릭터 불러오는 중...</div> : null}
          {!loadingCandidates && selectedSeriesId && candidates.length === 0 ? (
            <div className="empty-state">생성 가능한 캐릭터가 없습니다.</div>
          ) : null}

          {!loadingCandidates && candidates.length > 0 ? (
            <div className="generation-candidate-list">
              {candidates.map((candidate) => (
                <label key={candidate.id} className="generation-candidate-item">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(candidate.id)}
                    onChange={() => toggleCandidate(candidate.id)}
                  />
                  <div>
                    <strong>{candidate.character_tag}</strong>
                    <div className="generation-candidate-prompt">{candidate.generation_prompt}</div>
                  </div>
                </label>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      {queuePreview ? (
        <div className="panel generation-preview-panel">
          <h2 className="section-title">큐 미리보기</h2>
          <div className="generation-preview-meta">
            <span>queue: {queuePreview.queue_id}</span>
            <span>characters: {queuePreview.character_count}</span>
            <span>wildcard: {queuePreview.wildcard_path}</span>
          </div>
          <pre className="generation-prompt-block">{queuePreview.prompt_template}</pre>
          {queuePreview.skipped.length > 0 ? (
            <p className="field-help">건너뜀 {queuePreview.skipped.length}명 (미리보기 기준)</p>
          ) : null}
        </div>
      ) : null}

      {activeJob ? (
        <GenerationProgressPanel
          job={activeJob}
          onCancel={() => void cancelJob(activeJob.job_id)}
        />
      ) : null}

      {recentCompletedJobs.length > 0 ? (
        <div className="panel">
          <h2 className="section-title">최근 생성 작업</h2>
          <div className="generation-recent-grid">
            {recentCompletedJobs.map((job) => {
              const imageUrl = pendingReviewImageUrl(job.last_image_path);
              return (
                <div key={job.job_id} className="generation-recent-card">
                  <div className="generation-recent-header">
                    <strong>{job.series_tag}</strong>
                    <span className="badge">{job.status}</span>
                  </div>
                  <p>{job.message}</p>
                  {imageUrl ? <img src={imageUrl} alt={job.current_character_tag || "recent"} /> : null}
                  {job.status === "completed" || job.status === "failed" ? (
                    <button
                      className="btn btn-small btn-ghost"
                      type="button"
                      onClick={() => dismissJob(job.job_id)}
                    >
                      닫기
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </section>
  );
}
