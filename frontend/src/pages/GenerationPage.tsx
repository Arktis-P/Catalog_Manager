import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { GenerationProgressPanel } from "../components/GenerationProgressPanel";
import {
  GenerationPromptPipeline,
  wildcardTokenForSeries,
  wildcardTokenFromQueue,
} from "../components/GenerationPromptPipeline";
import { SeriesSearchSelect } from "../components/SeriesSearchSelect";
import { useGenerationJobs } from "../context/GenerationJobContext";
import type {
  AppSettings,
  GenerationCandidate,
  GenerationQueuePreview,
  GlobalGenerationCandidate,
  NaiaStatus,
  Series,
  SuggestLevelResponse,
} from "../types";

const MAX_GLOBAL_SELECTION = 300;

function pendingReviewImageUrl(imagePath: string | null | undefined): string | null {
  if (!imagePath) {
    return null;
  }
  const filename = imagePath.split(/[\\/]/).pop();
  return filename ? `/media/pending-review/${filename}` : null;
}

export function GenerationPage() {
  const {
    jobs,
    startGeneration,
    startCharacterGeneration,
    cancelJob,
    dismissJob,
    isGeneratingSeries,
    isGeneratingCharacters,
  } = useGenerationJobs();
  const [mode, setMode] = useState<"series" | "characters">("series");
  const [globalCandidates, setGlobalCandidates] = useState<GlobalGenerationCandidate[]>([]);
  const [globalStats, setGlobalStats] = useState({ total_completed: 0, already_generated: 0, remaining: 0 });
  const [globalSelectedIds, setGlobalSelectedIds] = useState<Set<number>>(() => new Set());
  const [globalSearch, setGlobalSearch] = useState("");
  const [globalPromptLevel, setGlobalPromptLevel] = useState(1);
  const [loadingGlobalCandidates, setLoadingGlobalCandidates] = useState(false);
  const [startingGlobal, setStartingGlobal] = useState(false);
  const [selectedSeries, setSelectedSeries] = useState<Series | null>(null);
  const [selectedSeriesId, setSelectedSeriesId] = useState<number | "">("");
  const [candidates, setCandidates] = useState<GenerationCandidate[]>([]);
  const [candidateStats, setCandidateStats] = useState({
    total_characters: 0,
    with_prompt: 0,
    confirmed_with_prompt: 0,
    unconfirmed_with_prompt: 0,
    needs_check_with_prompt: 0,
  });
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [promptLevel, setPromptLevel] = useState(1);
  const [requireConfirmed, setRequireConfirmed] = useState(true);
  const [showNeedsCheckOnly, setShowNeedsCheckOnly] = useState(false);
  const [characterSearch, setCharacterSearch] = useState("");
  const [naiaStatus, setNaiaStatus] = useState<NaiaStatus | null>(null);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [promptPrefix, setPromptPrefix] = useState("");
  const [promptSuffix, setPromptSuffix] = useState("");
  const [savingPrompts, setSavingPrompts] = useState(false);
  const [queuePreview, setQueuePreview] = useState<GenerationQueuePreview | null>(null);
  const [levelSuggestion, setLevelSuggestion] = useState<SuggestLevelResponse | null>(null);
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

  const activeCharacterJob = useMemo(
    () =>
      jobs.find(
        (job) =>
          job.job_type === "image_generation" &&
          job.series_id === 0 &&
          (job.status === "queued" || job.status === "running" || job.status === "paused"),
      ) ?? null,
    [jobs],
  );

  useEffect(() => {
    if (mode !== "characters") {
      return;
    }
    void (async () => {
      setLoadingGlobalCandidates(true);
      setError(null);
      try {
        const response = await api.listGlobalGenerationCandidates({
          search: globalSearch || undefined,
          limit: MAX_GLOBAL_SELECTION,
        });
        setGlobalCandidates(response.items);
        setGlobalStats({
          total_completed: response.total_completed,
          already_generated: response.already_generated,
          remaining: response.remaining,
        });
        setGlobalSelectedIds(new Set(response.items.map((item) => item.id)));
      } catch (err) {
        setError(err instanceof Error ? err.message : "캐릭터 목록을 불러오지 못했습니다.");
      } finally {
        setLoadingGlobalCandidates(false);
      }
    })();
  }, [mode, globalSearch]);

  const toggleGlobalCandidate = (id: number) => {
    setGlobalSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else if (next.size < MAX_GLOBAL_SELECTION) {
        next.add(id);
      }
      return next;
    });
  };

  const handleStartCharacterGeneration = async () => {
    if (globalSelectedIds.size === 0) {
      return;
    }
    setStartingGlobal(true);
    setError(null);
    try {
      await startCharacterGeneration(Array.from(globalSelectedIds), globalPromptLevel);
    } catch (err) {
      setError(err instanceof Error ? err.message : "이미지 생성 시작 실패");
    } finally {
      setStartingGlobal(false);
    }
  };

  useEffect(() => {
    void (async () => {
      setLoading(true);
      try {
        const [statusResponse, settingsResponse] = await Promise.all([
          api.getNaiaStatus(),
          api.getSettings(),
        ]);
        setNaiaStatus(statusResponse);
        setAppSettings(settingsResponse);
        setPromptPrefix(settingsResponse.generation_prompt_prefix);
        setPromptSuffix(settingsResponse.generation_prompt_suffix);
      } catch (err) {
        setError(err instanceof Error ? err.message : "NAIA 상태를 확인하지 못했습니다.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!selectedSeriesId) {
      setCandidates([]);
      setSelectedIds(new Set());
      setQueuePreview(null);
      setLevelSuggestion(null);
      setCandidateStats({
        total_characters: 0,
        with_prompt: 0,
        confirmed_with_prompt: 0,
        unconfirmed_with_prompt: 0,
        needs_check_with_prompt: 0,
      });
      return;
    }

    void (async () => {
      setLoadingCandidates(true);
      setError(null);
      try {
        const response = await api.listGenerationCandidates(selectedSeriesId, {
          require_confirmed: requireConfirmed,
          exclude_needs_check: !showNeedsCheckOnly,
          needs_check_only: showNeedsCheckOnly,
          search: characterSearch || undefined,
        });
        setCandidates(response.items);
        setCandidateStats({
          total_characters: response.total_characters,
          with_prompt: response.with_prompt,
          confirmed_with_prompt: response.confirmed_with_prompt,
          unconfirmed_with_prompt: response.unconfirmed_with_prompt,
          needs_check_with_prompt: response.needs_check_with_prompt,
        });
        const ids = showNeedsCheckOnly ? [] : response.items.map((item) => item.id);
        setSelectedIds(new Set(ids));
        if (typeof selectedSeriesId === "number" && ids.length > 0) {
          try {
            const suggestion = await api.suggestPromptLevel(selectedSeriesId, ids);
            setLevelSuggestion(suggestion);
          } catch {
            setLevelSuggestion(null);
          }
        } else {
          setLevelSuggestion(null);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "캐릭터 목록을 불러오지 못했습니다.");
      } finally {
        setLoadingCandidates(false);
      }
    })();
  }, [selectedSeriesId, requireConfirmed, showNeedsCheckOnly, characterSearch]);

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

  const handleSeriesChange = (seriesId: number | "", series?: Series | null) => {
    setSelectedSeriesId(seriesId);
    setSelectedSeries(series ?? null);
    if (series && (series.status === "tagged" || series.status === "generated" || series.all_appearance_collected)) {
      setRequireConfirmed(false);
    }
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

  const handleSavePrompts = async () => {
    setSavingPrompts(true);
    setError(null);
    try {
      const response = await api.updateSettings({
        generation_prompt_prefix: promptPrefix,
        generation_prompt_suffix: promptSuffix,
      });
      setAppSettings(response);
      setPromptPrefix(response.generation_prompt_prefix);
      setPromptSuffix(response.generation_prompt_suffix);
    } catch (err) {
      setError(err instanceof Error ? err.message : "프롬프트 저장 실패");
    } finally {
      setSavingPrompts(false);
    }
  };

  const handleStart = async () => {
    if (!selectedSeriesId) {
      return;
    }
    setStarting(true);
    setError(null);
    try {
      if (
        appSettings &&
        (promptPrefix !== appSettings.generation_prompt_prefix ||
          promptSuffix !== appSettings.generation_prompt_suffix)
      ) {
        await api.updateSettings({
          generation_prompt_prefix: promptPrefix,
          generation_prompt_suffix: promptSuffix,
        });
      }
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

  const selectedSeriesTag = selectedSeries?.series_tag ?? "";

  return (
    <section className="generation-page">
      <header className="page-header">
        <div>
          <h1 className="page-title">Generation</h1>
          <p className="page-description">
            시리즈별 generation_prompt를 NAIA 와일드카드로 보내고, NAIA API로 이미지를 생성한 뒤
            자동 검사를 거쳐 검수 대기 폴더에 저장합니다. 캐릭터당 기본{" "}
            {appSettings?.generation_images_per_character ?? 2}장 생성합니다.
          </p>
        </div>
      </header>

      {error ? <div className="error-banner">{error}</div> : null}

      <div className="review-mode-tabs" role="tablist" aria-label="Generation mode">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "series"}
          className={`review-mode-tab${mode === "series" ? " review-mode-tab--active" : ""}`}
          onClick={() => setMode("series")}
        >
          시리즈
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "characters"}
          className={`review-mode-tab${mode === "characters" ? " review-mode-tab--active" : ""}`}
          onClick={() => setMode("characters")}
        >
          캐릭터 목록
        </button>
      </div>

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

          {mode === "characters" ? (
            <>
              <h2 className="section-title">생성 대상 · 캐릭터 목록</h2>
              <div className="form-grid">
                <div className="field full-width">
                  <label htmlFor="generation-global-search">캐릭터 검색</label>
                  <input
                    id="generation-global-search"
                    value={globalSearch}
                    onChange={(event) => setGlobalSearch(event.target.value)}
                    placeholder="character tag"
                  />
                </div>
                <div className="field">
                  <label htmlFor="generation-global-level">Prompt Level</label>
                  <select
                    id="generation-global-level"
                    value={globalPromptLevel}
                    onChange={(event) => setGlobalPromptLevel(Number(event.target.value))}
                  >
                    <option value={1}>Level 1</option>
                    <option value={2}>Level 2</option>
                    <option value={3}>Level 3</option>
                    <option value={4}>Level 4</option>
                    <option value={5}>Level 5</option>
                  </select>
                </div>
                <div className="field full-width">
                  <p className="field-help">
                    특징 태그 수집 완료 + 아직 이미지가 생성되지 않은 캐릭터만 표시됩니다. 수집 완료{" "}
                    {globalStats.total_completed}명 · 이미 생성됨 {globalStats.already_generated}명 · 남음{" "}
                    {globalStats.remaining}명. 최대 {MAX_GLOBAL_SELECTION}개까지 선택 가능 (선택{" "}
                    {globalSelectedIds.size}개).
                  </p>
                </div>
              </div>
              <div className="modal-actions">
                <button
                  className="btn btn-primary"
                  type="button"
                  disabled={
                    globalSelectedIds.size === 0 || !naiaStatus?.ready || startingGlobal || isGeneratingCharacters()
                  }
                  onClick={() => void handleStartCharacterGeneration()}
                >
                  {startingGlobal
                    ? "시작 중..."
                    : isGeneratingCharacters()
                      ? "다른 캐릭터 목록 생성이 진행 중 · 대기열에 추가됨"
                      : "이미지 생성 시작"}
                </button>
              </div>
            </>
          ) : (
            <>
          <h2 className="section-title">생성 대상</h2>
          <div className="form-grid">
            <div className="field full-width">
              <label htmlFor="generation-series">시리즈</label>
              <SeriesSearchSelect
                value={selectedSeriesId}
                onChange={handleSeriesChange}
                disabled={loading}
              />
            </div>

            <div className="field">
              <label htmlFor="generation-level">
                Prompt Level
                {levelSuggestion ? (
                  <span
                    className="badge badge-info"
                    style={{ marginLeft: 8, cursor: "pointer" }}
                    title={`분포: ${Object.entries(levelSuggestion.breakdown).map(([lv, cnt]) => `Lv${lv}:${cnt}명`).join(", ")}`}
                    onClick={() => setPromptLevel(levelSuggestion.suggested_level)}
                  >
                    추천 Lv{levelSuggestion.suggested_level}
                  </span>
                ) : null}
              </label>
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
              <label htmlFor="generation-character-search">캐릭터 검색</label>
              <input
                id="generation-character-search"
                value={characterSearch}
                onChange={(event) => setCharacterSearch(event.target.value)}
                placeholder="character tag"
                disabled={!selectedSeriesId}
              />
            </div>

            <div className="field full-width">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={showNeedsCheckOnly}
                  onChange={(event) => setShowNeedsCheckOnly(event.target.checked)}
                />
                needs_check 캐릭터만 보기 (생성 대상에서 기본 제외됨)
              </label>
              {selectedSeriesId && candidateStats.needs_check_with_prompt > 0 ? (
                <p className="field-help">
                  needs_check {candidateStats.needs_check_with_prompt}명 · 시리즈 소속 검증 등으로 표시된 캐릭터입니다.
                </p>
              ) : null}
            </div>

            <div className="field full-width">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={requireConfirmed}
                  onChange={(event) => setRequireConfirmed(event.target.checked)}
                  disabled={showNeedsCheckOnly}
                />
                외형 태그 Confirm된 캐릭터만 포함 (Review 탭에서 확정한 경우)
              </label>
              {selectedSeriesId && candidateStats.with_prompt > 0 ? (
                <p className="field-help">
                  prompt {candidateStats.with_prompt}명 · Confirm {candidateStats.confirmed_with_prompt}명
                  {candidateStats.unconfirmed_with_prompt > 0
                    ? ` · 미확정 ${candidateStats.unconfirmed_with_prompt}명`
                    : ""}
                </p>
              ) : null}
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
                candidates.length === 0 ||
                showNeedsCheckOnly
              }
              onClick={() => void handleStart()}
            >
              {starting ? "시작 중..." : "이미지 생성 시작"}
            </button>
          </div>
            </>
          )}
        </div>

        <div className="panel generation-candidates">
          {mode === "characters" ? (
            <>
              <div className="section-header-row">
                <h2 className="section-title">캐릭터 목록</h2>
                {globalCandidates.length > 0 ? (
                  <button
                    className="btn btn-small"
                    type="button"
                    onClick={() =>
                      setGlobalSelectedIds((current) =>
                        current.size === globalCandidates.length
                          ? new Set()
                          : new Set(globalCandidates.slice(0, MAX_GLOBAL_SELECTION).map((item) => item.id)),
                      )
                    }
                  >
                    {globalSelectedIds.size === globalCandidates.length ? "전체 해제" : "전체 선택"}
                  </button>
                ) : null}
              </div>
              {loadingGlobalCandidates ? <div className="empty-state">캐릭터 불러오는 중...</div> : null}
              {!loadingGlobalCandidates && globalCandidates.length === 0 ? (
                <div className="empty-state">
                  생성 가능한 캐릭터가 없습니다. (특징 태그 수집 완료 + 미생성 캐릭터만 표시)
                </div>
              ) : null}
              {!loadingGlobalCandidates && globalCandidates.length > 0 ? (
                <div className="generation-candidate-list">
                  {globalCandidates.map((candidate) => (
                    <label key={candidate.id} className="generation-candidate-item">
                      <input
                        type="checkbox"
                        checked={globalSelectedIds.has(candidate.id)}
                        onChange={() => toggleGlobalCandidate(candidate.id)}
                      />
                      <div>
                        <strong>{candidate.character_tag}</strong>
                        <span className="field-help"> · {candidate.post_count.toLocaleString()} posts</span>
                      </div>
                    </label>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <>
          <div className="section-header-row">
            <h2 className="section-title">
              캐릭터 목록
              {selectedSeriesTag ? ` · ${selectedSeriesTag}` : ""}
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
            <div className="empty-state">
              {candidateStats.with_prompt > 0 && requireConfirmed ? (
                <>
                  generation_prompt는 {candidateStats.with_prompt}명 있으나, Confirm된 캐릭터가 없습니다.
                  시리즈 status가 <strong>tagged</strong>여도 Review Confirm은 별도 단계입니다.
                  <button
                    className="btn btn-small"
                    type="button"
                    style={{ marginTop: 12 }}
                    onClick={() => setRequireConfirmed(false)}
                  >
                    미확정 캐릭터도 포함
                  </button>
                </>
              ) : (
                "생성 가능한 캐릭터가 없습니다. 외형 태그 추출을 먼저 실행하세요."
              )}
            </div>
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
                    {candidate.status === "needs_check" ? (
                      <span className="badge badge-warning" style={{ marginLeft: 8 }}>
                        needs_check
                      </span>
                    ) : null}
                    {candidate.needs_check_reason ? (
                      <div className="field-help">{candidate.needs_check_reason}</div>
                    ) : null}
                    <div className="generation-candidate-prompt">{candidate.generation_prompt}</div>
                  </div>
                </label>
              ))}
            </div>
          ) : null}
            </>
          )}
        </div>
      </div>

      {appSettings ? (
        <div className="panel generation-prompt-panel">
          <div className="section-header-row">
            <h2 className="section-title">프롬프트 구조</h2>
            <button
              className="btn btn-small"
              type="button"
              disabled={savingPrompts}
              onClick={() => void handleSavePrompts()}
            >
              {savingPrompts ? "저장 중..." : "프롬프트 저장"}
            </button>
          </div>
          <GenerationPromptPipeline
            prefix={promptPrefix}
            suffix={promptSuffix}
            wildcardToken={
              queuePreview
                ? wildcardTokenFromQueue(queuePreview.queue_id)
                : wildcardTokenForSeries(selectedSeriesTag || undefined)
            }
            onPrefixChange={setPromptPrefix}
            onSuffixChange={setPromptSuffix}
          />
          <p className="field-help">
            큐 생성 시 Wildcard 이름이 확정됩니다. 저장 시 자동 검사: 눈/손 디테일 (손이 가려지면 손 검사 생략).
          </p>
        </div>
      ) : null}

      {queuePreview ? (
        <div className="panel generation-preview-panel">
          <h2 className="section-title">큐 미리보기</h2>
          <div className="generation-preview-meta">
            <span>queue: {queuePreview.queue_id}</span>
            <span>characters: {queuePreview.character_count}</span>
            <span>per character: {appSettings?.generation_images_per_character ?? 2} images</span>
            <span>wildcard: {queuePreview.wildcard_path}</span>
          </div>
          <GenerationPromptPipeline
            prefix={queuePreview.prompt_prefix}
            suffix={queuePreview.prompt_suffix}
            wildcardToken={wildcardTokenFromQueue(queuePreview.queue_id)}
            readOnly
          />
          <span className="field-label">전체 조합 예시</span>
          <pre className="generation-prompt-block">{queuePreview.prompt_template}</pre>
          <span className="field-label">Negative</span>
          <pre className="generation-prompt-block">{queuePreview.negative_prompt}</pre>
          {queuePreview.skipped.length > 0 ? (
            <p className="field-help">건너뜀 {queuePreview.skipped.length}명 (미리보기 기준)</p>
          ) : null}
        </div>
      ) : null}

      {mode === "characters" ? (
        activeCharacterJob ? (
          <GenerationProgressPanel
            job={activeCharacterJob}
            onCancel={() => void cancelJob(activeCharacterJob.job_id)}
          />
        ) : null
      ) : activeJob ? (
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
