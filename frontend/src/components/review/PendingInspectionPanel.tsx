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
};

type RunScope = "all" | "page" | null;

const BATCH_SIZE = 10;
const PAGE_TEST_LIMIT = 30;
const inspectionStopRequests = new Set<string>();

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

function inspectionQuery(limit?: number): URLSearchParams {
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
      for (let index = 0; index < characterIds.length; index += BATCH_SIZE) {
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

        const chunk = characterIds.slice(index, index + BATCH_SIZE);
        const query = inspectionQuery();
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
        task = addInspectionResult(
          task,
          result,
          processed,
          `현재 페이지 Pending 자동 검사 · ${processed.toLocaleString()}/${characterIds.length.toLocaleString()} · 실제 검사 ${inspected.toLocaleString()} · 재생성 ${regenerated.toLocaleString()} · 자동완료 ${autoCompleted.toLocaleString()}`,
        );
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

  if (!stats) {
    return error ? <div className="alert alert-error">{error}</div> : null;
  }

  const displayedMessage = message ?? activeInspectionJob?.message ?? null;

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
            완료된 리뷰는 건드리지 않습니다. 기존 이미지가 있는 Pending만 검사하며 명백한 실패만 최대 2회 재생성합니다.
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
          <button type="button" className="btn" disabled={running} onClick={() => void loadStats()}>
            상태 새로고침
          </button>
        </div>
      </div>
    </section>
  );
}
