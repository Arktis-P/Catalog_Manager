import { useCallback, useEffect, useMemo, useState } from "react";
import { useGenerationJobs } from "../../context/GenerationJobContext";
import type { V2GenerationJobState } from "../../types";

type InspectionStats = {
  pending_total: number;
  pending_with_image: number;
  pending_without_image: number;
  remaining: number;
  current: number;
  inspection_version: string;
  // 서버가 기록한 페이지 테스트 대상 수. 재시작 전 구버전 백엔드에서는 없을 수 있다.
  test_tracked?: number;
};

type InspectionSummary = {
  requested_limit: number;
  inspected: number;
  profile_built: number;
  passed: number;
  warnings: number;
  rejected: number;
  characters_regenerated: number;
  regeneration_images: number;
  rejected_files_removed: number;
  auto_completed: number;
  audit_kept_pending: number;
  prefilled_pending: number;
  suggested_only: number;
  ratings: Record<string, number>;
  errors: string[];
  inspected_character_ids?: number[];
  skipped_current_version?: number;
  tagger_success?: number;
  tagger_error?: number;
  semantic_pass?: number;
  semantic_warning?: number;
  semantic_reject?: number;
  reference_loaded?: number;
  reference_failed?: number;
  regeneration_requested?: number;
  character_diagnostics?: Array<{
    character_id: number;
    character_tag?: string;
    latest_image_id?: number | null;
    image_count_for_character?: number;
    inspected?: boolean;
    identity_repair_stage?: string | null;
    semantic_repair_stage?: string | null;
    reject_reason?: string | null;
    regeneration_requested?: number;
    regeneration_completed?: number;
    reinspection_completed?: number;
    final_action?: string;
  }>;
};

type InspectionResetSummary = {
  requested: number;
  matched: number;
  images_reset: number;
  reviews_reset: number;
  profiles_reset: number;
  test_tracked_remaining?: number;
};

type RunScope = "all" | "page" | null;

const BATCH_SIZE = 10;
// Page tests resolve every repair stage for one character synchronously per request, so
// request one character at a time to keep the top-level progress bar moving (1/30, 2/30…)
// and let a stop request take effect quickly.
const PAGE_TEST_BATCH_SIZE = 1;
const PAGE_TEST_LIMIT = 30;
const TEST_RESET_ENABLED = true;
const inspectionStopRequests = new Set<string>();

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

function inspectionQuery(limit?: number, overrides?: Record<string, string>): URLSearchParams {
  const query = new URLSearchParams({
    auto_regenerate: "true",
    max_regenerations: "2",
    auto_complete: "true",
    audit_sample_rate: "0.10",
    cleanup_rejected: "true",
  });
  if (limit != null) {
    query.set("limit", String(limit));
  }
  if (overrides) {
    for (const [key, value] of Object.entries(overrides)) {
      query.set(key, value);
    }
  }
  return query;
}

function currentPageCharacterIds(): number[] {
  const nodes = document.querySelectorAll<HTMLElement>(
    ".v2-review-grid:not(.v2-non-human-grid) [data-character-id]",
  );
  const ids: number[] = [];
  const seen = new Set<number>();
  for (const node of nodes) {
    if (node.offsetParent === null) continue;
    const id = Number(node.dataset.characterId);
    if (!Number.isFinite(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    ids.push(id);
    if (ids.length >= PAGE_TEST_LIMIT) break;
  }
  return ids;
}

function makeInspectionJob(scope: Exclude<RunScope, null>, total: number): V2GenerationJobState {
  const startedAt = new Date().toISOString();
  const scopeLabel = scope === "page" ? "현재 페이지 Pending 자동 검사" : "전체 Pending 자동 검사";
  return {
    job_id: `pending-inspection-${scope}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    kind: "generate",
    status: "running",
    phase: `pending_inspection_${scope}`,
    message: `${scopeLabel} · 0/${total.toLocaleString()}`,
    current: 0,
    total,
    completed: 0,
    failed: 0,
    character_tag: "Pending 자동 검사",
    current_character_tag: scopeLabel,
    character_id: null,
    generation_status: null,
    generation_attempts: 0,
    total_generation_attempts: 0,
    prompt_variant_attempts: {
      inspected: 0,
      regenerated: 0,
      auto_completed: 0,
      prefilled: 0,
      audit: 0,
      files_removed: 0,
      errors: 0,
    },
    image_id: null,
    quality_status: null,
    quality_reasons: [],
    identity_status: null,
    identity_reasons: [],
    is_provisional: null,
    last_failure_reason: null,
    errors: [],
    started_at: startedAt,
    finished_at: null,
  };
}

function addInspectionResult(
  job: V2GenerationJobState,
  result: InspectionSummary,
  current: number,
  message: string,
): V2GenerationJobState {
  const metrics = job.prompt_variant_attempts;
  const nextErrors = result.errors.map((error) => ({ error }));
  return {
    ...job,
    current: Math.min(job.total, Math.max(job.current, current)),
    completed: job.completed + result.inspected,
    failed: job.failed + result.errors.length,
    generation_attempts: job.generation_attempts + result.characters_regenerated,
    total_generation_attempts: job.total_generation_attempts + result.regeneration_images,
    prompt_variant_attempts: {
      inspected: (metrics.inspected ?? 0) + result.inspected,
      regenerated: (metrics.regenerated ?? 0) + result.characters_regenerated,
      auto_completed: (metrics.auto_completed ?? 0) + result.auto_completed,
      prefilled: (metrics.prefilled ?? 0) + result.prefilled_pending,
      audit: (metrics.audit ?? 0) + result.audit_kept_pending,
      files_removed: (metrics.files_removed ?? 0) + result.rejected_files_removed,
      errors: (metrics.errors ?? 0) + result.errors.length,
    },
    errors: [...job.errors, ...nextErrors],
    message,
  };
}

function finishInspectionJob(
  job: V2GenerationJobState,
  status: "completed" | "failed" | "cancelled",
  message: string,
  failureReason?: string,
): V2GenerationJobState {
  return {
    ...job,
    status,
    current: status === "completed" ? job.total : job.current,
    message,
    last_failure_reason: failureReason ?? null,
    finished_at: new Date().toISOString(),
  };
}

export function PendingInspectionPanel() {
  const [stats, setStats] = useState<InspectionStats | null>(null);
  const [runScope, setRunScope] = useState<RunScope>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const { v2Jobs, upsertLocalV2Job } = useGenerationJobs();

  const activeInspectionJob = useMemo(
    () =>
      v2Jobs.find(
        (job) =>
          job.phase.startsWith("pending_inspection") &&
          (job.status === "queued" || job.status === "running" || job.status === "paused"),
      ) ?? null,
    [v2Jobs],
  );
  const running = runScope !== null || activeInspectionJob !== null;

  const loadStats = useCallback(async () => {
    const response = await fetch("/api/review/v2/pending-inspection/stats");
    const next = await readJson<InspectionStats>(response);
    setStats(next);
    return next;
  }, []);

  useEffect(() => {
    void loadStats().catch((err) => {
      setError(err instanceof Error ? err.message : "자동 검사 상태를 불러오지 못했습니다.");
    });
  }, [loadStats]);

  const stop = useCallback(() => {
    if (!activeInspectionJob) return;
    inspectionStopRequests.add(activeInspectionJob.job_id);
    const next = {
      ...activeInspectionJob,
      message: `중지 요청됨 · 현재 ${BATCH_SIZE}개 배치가 끝나면 멈춥니다. (${activeInspectionJob.current}/${activeInspectionJob.total})`,
    };
    upsertLocalV2Job(next);
    setMessage(next.message);
  }, [activeInspectionJob, upsertLocalV2Job]);

  const run = useCallback(async () => {
    if (running) return;
    setRunScope("all");
    setError(null);

    let task: V2GenerationJobState | null = null;
    try {
      let current = await loadStats();
      if (current.remaining <= 0) {
        setMessage("자동 검사할 Pending 이미지가 없습니다.");
        return;
      }

      const total = current.remaining;
      task = makeInspectionJob("all", total);
      upsertLocalV2Job(task);
      setMessage(task.message);
      let beforeRemaining = current.remaining;

      while (current.remaining > 0) {
        if (inspectionStopRequests.has(task.job_id)) {
          task = finishInspectionJob(
            task,
            "cancelled",
            `사용자 중지 · ${task.current.toLocaleString()}/${task.total.toLocaleString()} 처리`,
          );
          inspectionStopRequests.delete(task.job_id);
          upsertLocalV2Job(task);
          setMessage(task.message);
          return;
        }

        const query = inspectionQuery(BATCH_SIZE);
        const response = await fetch(`/api/review/v2/pending-inspection/run?${query.toString()}`, {
          method: "POST",
        });
        const result = await readJson<InspectionSummary>(response);
        current = await loadStats();
        const processed = Math.max(0, Math.min(total, total - current.remaining));
        const metrics = task.prompt_variant_attempts;
        const inspected = (metrics.inspected ?? 0) + result.inspected;
        const regenerated = (metrics.regenerated ?? 0) + result.characters_regenerated;
        const autoCompleted = (metrics.auto_completed ?? 0) + result.auto_completed;
        task = addInspectionResult(
          task,
          result,
          processed,
          `전체 Pending 자동 검사 · ${processed.toLocaleString()}/${total.toLocaleString()} · 검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()}`,
        );
        upsertLocalV2Job(task);
        setMessage(task.message);

        if (inspectionStopRequests.has(task.job_id)) {
          task = finishInspectionJob(
            task,
            "cancelled",
            `사용자 중지 · ${task.current.toLocaleString()}/${task.total.toLocaleString()} 처리`,
          );
          inspectionStopRequests.delete(task.job_id);
          upsertLocalV2Job(task);
          setMessage(task.message);
          return;
        }

        if (current.remaining >= beforeRemaining) {
          const failure = result.errors.length
            ? `같은 배치가 진행되지 않았습니다. 누적 오류 ${task.failed}개를 확인하세요.`
            : "같은 배치가 진행되지 않았습니다. 상태를 확인한 뒤 다시 실행하세요.";
          task = finishInspectionJob(task, "failed", "Pending 자동 검사 안전 중지", failure);
          upsertLocalV2Job(task);
          setError(failure);
          return;
        }
        beforeRemaining = current.remaining;
      }

      const metrics = task.prompt_variant_attempts;
      task = finishInspectionJob(
        task,
        "completed",
        `전체 Pending 자동 검사 완료 · ${task.total.toLocaleString()}/${task.total.toLocaleString()} · 검사 ${(metrics.inspected ?? 0).toLocaleString()} · 재생성 ${(metrics.regenerated ?? 0).toLocaleString()} · 자동완료 ${(metrics.auto_completed ?? 0).toLocaleString()}`,
      );
      upsertLocalV2Job(task);
      setMessage(task.message);
    } catch (err) {
      const failure = err instanceof Error ? err.message : "pending 자동 검사 중 오류가 발생했습니다.";
      if (task) {
        task = finishInspectionJob(task, "failed", "Pending 자동 검사 실패", failure);
        upsertLocalV2Job(task);
      }
      setError(failure);
      await loadStats().catch(() => undefined);
    } finally {
      setRunScope(null);
    }
  }, [loadStats, running, upsertLocalV2Job]);

  const runCurrentPage = useCallback(async () => {
    if (running) return;
    const characterIds = currentPageCharacterIds();
    if (characterIds.length === 0) {
      setError("현재 화면에서 검사할 V2 카드의 ID를 찾지 못했습니다.");
      return;
    }

    setRunScope("page");
    setError(null);
    let task = makeInspectionJob("page", characterIds.length);
    upsertLocalV2Job(task);
    setMessage(task.message);

    try {
      let processed = 0;
      for (let index = 0; index < characterIds.length; index += PAGE_TEST_BATCH_SIZE) {
        if (inspectionStopRequests.has(task.job_id)) {
          task = finishInspectionJob(
            task,
            "cancelled",
            `사용자 중지 · ${task.current.toLocaleString()}/${task.total.toLocaleString()} 처리`,
          );
          inspectionStopRequests.delete(task.job_id);
          upsertLocalV2Job(task);
          setMessage(task.message);
          return;
        }

        const chunk = characterIds.slice(index, index + PAGE_TEST_BATCH_SIZE);
        const query = inspectionQuery(undefined, {
          force_recheck: "true",
          // Page tests keep rejected files for diagnosis unless the operator asks otherwise.
          cleanup_rejected: "false",
        });
        const response = await fetch(`/api/review/v2/pending-inspection/run-selected?${query.toString()}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ character_ids: chunk }),
        });
        const result = await readJson<InspectionSummary>(response);
        processed += chunk.length;
        const metrics = task.prompt_variant_attempts;
        const inspected = (metrics.inspected ?? 0) + result.inspected;
        const regenerated = (metrics.regenerated ?? 0) + result.characters_regenerated;
        const autoCompleted = (metrics.auto_completed ?? 0) + result.auto_completed;
        const taggerOk = (metrics.tagger_success as number | undefined ?? 0) + (result.tagger_success ?? 0);
        const taggerErr = (metrics.tagger_error as number | undefined ?? 0) + (result.tagger_error ?? 0);
        const semanticReject = (metrics.semantic_reject as number | undefined ?? 0) + (result.semantic_reject ?? 0);
        const reinpected = (result.character_diagnostics ?? []).reduce(
          (sum, row) => sum + (row.reinspection_completed ?? 0),
          0,
        );
        const autoZero = (result.character_diagnostics ?? []).filter((row) => row.final_action === "0성").length;
        task = addInspectionResult(
          task,
          result,
          processed,
          `현재 페이지 Pending 자동 검사 · ${processed.toLocaleString()}/${characterIds.length.toLocaleString()} · 실제 검사 ${inspected.toLocaleString()} · tagger ${taggerOk}/${taggerErr} · reject ${semanticReject.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 재검사 ${reinpected.toLocaleString()} · 0성 ${autoZero.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()}`,
        );
        task = {
          ...task,
          prompt_variant_attempts: {
            ...task.prompt_variant_attempts,
            tagger_success: taggerOk,
            tagger_error: taggerErr,
            semantic_reject: semanticReject,
            semantic_pass: (metrics.semantic_pass as number | undefined ?? 0) + (result.semantic_pass ?? 0),
            semantic_warning: (metrics.semantic_warning as number | undefined ?? 0) + (result.semantic_warning ?? 0),
            reinspection_completed: (metrics.reinspection_completed as number | undefined ?? 0) + reinpected,
          },
        };
        upsertLocalV2Job(task);
        setMessage(task.message);
        await loadStats();
      }

      if (inspectionStopRequests.has(task.job_id)) {
        task = finishInspectionJob(
          task,
          "cancelled",
          `사용자 중지 · ${task.current.toLocaleString()}/${task.total.toLocaleString()} 처리`,
        );
        inspectionStopRequests.delete(task.job_id);
      } else {
        const metrics = task.prompt_variant_attempts;
        task = finishInspectionJob(
          task,
          "completed",
          `현재 페이지 테스트 완료 · ${task.total.toLocaleString()}/${task.total.toLocaleString()} 확인 · 실제 검사 ${(metrics.inspected ?? 0).toLocaleString()} · 재생성 ${(metrics.regenerated ?? 0).toLocaleString()} · 자동완료 ${(metrics.auto_completed ?? 0).toLocaleString()}`,
        );
      }
      upsertLocalV2Job(task);
      setMessage(`${task.message} · 아래 V2 목록은 새로고침하면 결과가 반영됩니다.`);
    } catch (err) {
      const failure = err instanceof Error ? err.message : "현재 페이지 테스트 검사 중 오류가 발생했습니다.";
      task = finishInspectionJob(task, "failed", "현재 페이지 Pending 자동 검사 실패", failure);
      upsertLocalV2Job(task);
      setError(failure);
      await loadStats().catch(() => undefined);
    } finally {
      setRunScope(null);
    }
  }, [loadStats, running, upsertLocalV2Job]);

  const resetTestResults = useCallback(async () => {
    if (!TEST_RESET_ENABLED || running || resetting) return;

    // 서버가 페이지 테스트 대상을 직접 기록하므로 새로고침 후에도 초기화할 수 있다.
    // 추적 기록이 없을 때만 현재 화면에 보이는 카드를 대상으로 되돌린다.
    const tracked = stats?.test_tracked ?? 0;
    const fallbackIds = tracked > 0 ? [] : currentPageCharacterIds();
    if (tracked === 0 && fallbackIds.length === 0) {
      setError("초기화할 테스트 항목이 없습니다.");
      return;
    }

    const confirmed = window.confirm(
      (tracked > 0
        ? `페이지 테스트로 검사한 ${tracked.toLocaleString()}개 항목의 검사 결과를 초기화합니다. `
        : `추적된 테스트 기록이 없어 현재 화면에 보이는 ${fallbackIds.length.toLocaleString()}개 항목의 검사 결과를 초기화합니다. `) +
        "재생성된 이미지 파일과 직접 입력한 검수 결과는 그대로 유지합니다. 계속할까요?",
    );
    if (!confirmed) return;

    setResetting(true);
    setError(null);
    try {
      const response = await fetch("/api/review/v2/pending-inspection/reset-selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ character_ids: fallbackIds }),
      });
      const result = await readJson<InspectionResetSummary>(response);
      setMessage(
        `테스트 검사 초기화 완료 · 대상 ${result.matched.toLocaleString()} · 이미지 검사 ${result.images_reset.toLocaleString()} · ` +
          `자동 레이팅 ${result.reviews_reset.toLocaleString()} · 참조 캐시 ${result.profiles_reset.toLocaleString()} 초기화 · ` +
          `남은 추적 ${(result.test_tracked_remaining ?? 0).toLocaleString()} · 이미지 파일은 유지`,
      );
      await loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "테스트 검사 결과 초기화에 실패했습니다.");
    } finally {
      setResetting(false);
    }
  }, [loadStats, resetting, running, stats]);

  if (!stats) {
    return error ? <div className="alert alert-error">{error}</div> : null;
  }

  const displayedMessage = message ?? activeInspectionJob?.message ?? null;
  const trackedCount = stats.test_tracked ?? 0;

  return (
    <section className="panel" aria-label="Pending 자동 검사">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
          padding: "12px 16px",
        }}
      >
        <div>
          <strong>Pending 자동 검사</strong>
          <div className="page-description" style={{ marginTop: 4 }}>
            완료된 리뷰는 건드리지 않습니다. 기존 이미지가 있는 Pending만 최신 이미지 기준으로 검사하며, 외형 repair 후 semantic repair를 적용하고 재생성본을 다시 검사합니다.
            참조 이미지는 저장하지 않고 필요한 경우에만 Danbooru 태그 통계를 작은 캐시로 사용합니다.
          </div>
          <div style={{ marginTop: 6 }}>
            전체 리뷰 대기 <strong>{stats.pending_total.toLocaleString()}</strong> · 자동 검사 가능(이미지 있음){" "}
            <strong>{stats.pending_with_image.toLocaleString()}</strong> · 이미지 없음{" "}
            <strong>{stats.pending_without_image.toLocaleString()}</strong>
          </div>
          <div style={{ marginTop: 4 }}>
            자동 검사 완료 {stats.current.toLocaleString()} / {stats.pending_with_image.toLocaleString()} · 남음{" "}
            <strong>{stats.remaining.toLocaleString()}</strong>
            {TEST_RESET_ENABLED ? (
              <> · 테스트 초기화 추적 <strong>{trackedCount.toLocaleString()}</strong></>
            ) : null}
          </div>
          {displayedMessage ? <div style={{ marginTop: 6 }}>{displayedMessage}</div> : null}
          {error ? <div className="alert alert-error" style={{ marginTop: 6 }}>{error}</div> : null}
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {running ? (
            <button type="button" className="btn" onClick={stop} disabled={!activeInspectionJob}>
              현재 배치 후 중지
            </button>
          ) : (
            <>
              <button
                type="button"
                className="btn"
                onClick={() => void runCurrentPage()}
                title="아래 V2 검수 화면에 현재 표시된 카드 중 최대 30개만 먼저 검사합니다."
              >
                현재 페이지 최대 30개 테스트
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={stats.remaining <= 0}
                onClick={() => void run()}
              >
                남은 Pending 자동 검사
              </button>
            </>
          )}
          {TEST_RESET_ENABLED ? (
            <button
              type="button"
              className="btn"
              disabled={running || resetting}
              onClick={() => void resetTestResults()}
              title="페이지 테스트로 실제 검사한 항목의 검사 메타데이터와 테스트 자동 판정만 초기화합니다. 추적 기록이 없으면 현재 화면의 카드를 대상으로 합니다. 재생성된 이미지 파일과 직접 입력한 결과는 유지합니다."
            >
              {resetting
                ? "테스트 결과 초기화 중..."
                : trackedCount > 0
                  ? `테스트 결과 초기화 (${trackedCount.toLocaleString()})`
                  : "현재 페이지 검사 결과 초기화"}
            </button>
          ) : null}
          <button type="button" className="btn" disabled={running || resetting} onClick={() => void loadStats()}>
            상태 새로고침
          </button>
        </div>
      </div>
    </section>
  );
}