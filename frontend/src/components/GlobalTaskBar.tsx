import { useMemo } from "react";
import { CatalogProgressPanel } from "./CatalogProgressPanel";
import { CollectProgressPanel } from "./CollectProgressPanel";
import { GenerationProgressPanel } from "./GenerationProgressPanel";
import { RelevanceProgressPanel } from "./RelevanceProgressPanel";
import { ReviewRegenerateProgressPanel } from "./ReviewRegenerateProgressPanel";
import { V2GenerationProgressPanel } from "./V2GenerationProgressPanel";
import { useCharacterCatalogJobs } from "../context/CharacterCatalogJobContext";
import { useCollectJobs } from "../context/CollectJobContext";
import { useGenerationJobs } from "../context/GenerationJobContext";
import { useReviewRegenerateJobs } from "../context/ReviewRegenerateContext";
import type {
  CatalogJob,
  CollectJob,
  RelevanceCollectJob,
  ReviewRegenerateJob,
  V2GenerationJobState,
} from "../types";

function jobSortRank(job: { status: string }): number {
  if (job.status === "running") {
    return 0;
  }
  if (job.status === "paused") {
    return 1;
  }
  if (job.status === "queued") {
    return 2;
  }
  if (job.status === "failed") {
    return 3;
  }
  return 4;
}

type ActiveJobEntry =
  | { kind: "collect"; job: CollectJob }
  | { kind: "generation"; job: CollectJob }
  | { kind: "catalog"; job: CatalogJob }
  | { kind: "regenerate"; job: ReviewRegenerateJob }
  | { kind: "relevance"; job: RelevanceCollectJob }
  | { kind: "v2"; job: V2GenerationJobState };

const VISIBLE_STATUSES = new Set(["queued", "running", "paused", "completed", "failed", "cancelled"]);

interface GlobalTaskBarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function GlobalTaskBar({ collapsed, onToggleCollapsed }: GlobalTaskBarProps) {
  const {
    jobs: collectJobs,
    cancelJob: cancelCollectJob,
    pauseJob: pauseCollectJob,
    resumeJob: resumeCollectJob,
    dismissJob: dismissCollectJob,
    lastError: collectError,
    clearLastError: clearCollectError,
  } = useCollectJobs();
  const {
    jobs: generationJobs,
    dismissJob: dismissGenerationJob,
    cancelJob,
    pauseJob: pauseGenerationJob,
    resumeJob: resumeGenerationJob,
    lastError: generationError,
    clearLastError: clearGenerationError,
    v2Jobs,
    cancelV2Job,
    pauseV2Job,
    resumeV2Job,
    dismissV2Job,
  } = useGenerationJobs();
  const {
    jobs: catalogJobs,
    cancelJob: cancelCatalogJob,
    pauseJob: pauseCatalogJob,
    resumeJob: resumeCatalogJob,
    dismissJob: dismissCatalogJob,
    lastError: catalogError,
    clearLastError: clearCatalogError,
    relevanceJobs,
    cancelRelevanceJob,
    pauseRelevanceJob,
    resumeRelevanceJob,
    dismissRelevanceJob,
  } = useCharacterCatalogJobs();
  const { jobs: regenerateJobs, dismissJob: dismissRegenerateJob } = useReviewRegenerateJobs();

  const activeJobs = useMemo(() => {
    const entries: ActiveJobEntry[] = [
      ...collectJobs.map((job): ActiveJobEntry => ({ kind: "collect", job })),
      ...generationJobs.map((job): ActiveJobEntry => ({ kind: "generation", job })),
      ...catalogJobs.map((job): ActiveJobEntry => ({ kind: "catalog", job })),
      ...regenerateJobs.map((job): ActiveJobEntry => ({ kind: "regenerate", job })),
      ...relevanceJobs.map((job): ActiveJobEntry => ({ kind: "relevance", job })),
      ...v2Jobs.map((job): ActiveJobEntry => ({ kind: "v2", job })),
    ];
    return entries
      .filter((entry) => VISIBLE_STATUSES.has(entry.job.status))
      .sort(
        (a, b) => jobSortRank(a.job) - jobSortRank(b.job) || b.job.started_at.localeCompare(a.job.started_at),
      );
  }, [collectJobs, generationJobs, catalogJobs, regenerateJobs, relevanceJobs, v2Jobs]);

  const dismissibleJobs = useMemo(
    () =>
      activeJobs.filter(
        (entry) =>
          entry.job.status === "completed" || entry.job.status === "failed" || entry.job.status === "cancelled",
      ),
    [activeJobs],
  );

  const dismissAllCompleted = () => {
    for (const entry of dismissibleJobs) {
      switch (entry.kind) {
        case "regenerate":
          dismissRegenerateJob(entry.job.job_id);
          break;
        case "generation":
          dismissGenerationJob(entry.job.job_id);
          break;
        case "catalog":
          dismissCatalogJob(entry.job.job_id);
          break;
        case "relevance":
          dismissRelevanceJob(entry.job.job_id);
          break;
        case "v2":
          dismissV2Job(entry.job.job_id);
          break;
        default:
          dismissCollectJob(entry.job.job_id);
      }
    }
  };

  const lastError = collectError || generationError || catalogError;

  const queuedCount = useMemo(
    () => activeJobs.filter((entry) => entry.job.status === "queued").length,
    [activeJobs],
  );
  const runningCount = useMemo(
    () => activeJobs.filter((entry) => entry.job.status === "running").length,
    [activeJobs],
  );
  const pausedCount = useMemo(
    () => activeJobs.filter((entry) => entry.job.status === "paused").length,
    [activeJobs],
  );
  const failedCount = useMemo(
    () => activeJobs.filter((entry) => entry.job.status === "failed").length,
    [activeJobs],
  );
  const completedCount = useMemo(
    () => activeJobs.filter((entry) => entry.job.status === "completed").length,
    [activeJobs],
  );

  return (
    <section className={`global-task-bar${collapsed ? " global-task-bar--collapsed" : ""}`} aria-label="백그라운드 작업">
      <div className="task-summary-bar">
        <button
          className="task-sidebar-toggle"
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "작업 패널 펼치기" : "작업 패널 접기"}
          title={collapsed ? "작업 패널 펼치기" : "작업 패널 접기"}
        >
          <span aria-hidden="true">{collapsed ? "›" : "‹"}</span>
        </button>
        <span className="task-summary-count" aria-live="polite">
          {activeJobs.length === 0 && !lastError
            ? "작업 없음"
            : `실행 ${runningCount} · 일시정지 ${pausedCount} · 대기 ${queuedCount} · 실패 ${failedCount} · 완료 ${completedCount}`}
        </span>
        {!collapsed && dismissibleJobs.length > 0 ? (
          <button className="btn btn-small" type="button" onClick={dismissAllCompleted}>
            완료 지우기 ({dismissibleJobs.length})
          </button>
        ) : null}
      </div>

      {!collapsed ? <div className="global-task-bar-inner">
        {lastError ? (
          <div className="error-banner global-task-error">
            <span>{lastError}</span>
            <button
              className="btn btn-small"
              type="button"
              onClick={() => {
                clearCollectError();
                clearGenerationError();
                clearCatalogError();
              }}
            >
              Dismiss
            </button>
          </div>
        ) : null}
        <div className="global-task-bar-jobs">
          {activeJobs.map((entry) => {
            switch (entry.kind) {
              case "regenerate":
                return (
                  <ReviewRegenerateProgressPanel
                    key={entry.job.job_id}
                    job={entry.job}
                    onDismiss={
                      entry.job.status === "completed" || entry.job.status === "failed"
                        ? () => dismissRegenerateJob(entry.job.job_id)
                        : undefined
                    }
                  />
                );
              case "generation":
                return (
                  <GenerationProgressPanel
                    key={entry.job.job_id}
                    job={entry.job}
                    onCancel={
                      entry.job.status === "queued" || entry.job.status === "running" || entry.job.status === "paused"
                        ? () => void cancelJob(entry.job.job_id)
                        : undefined
                    }
                    onPause={entry.job.status === "running" ? () => void pauseGenerationJob(entry.job.job_id) : undefined}
                    onResume={entry.job.status === "paused" ? () => void resumeGenerationJob(entry.job.job_id) : undefined}
                    onDismiss={
                      entry.job.status === "completed" || entry.job.status === "failed" || entry.job.status === "cancelled"
                        ? () => dismissGenerationJob(entry.job.job_id)
                        : undefined
                    }
                  />
                );
              case "catalog":
                return (
                  <CatalogProgressPanel
                    key={entry.job.job_id}
                    job={entry.job}
                    onCancel={
                      entry.job.status === "queued" || entry.job.status === "running" || entry.job.status === "paused"
                        ? () => void cancelCatalogJob(entry.job.job_id)
                        : undefined
                    }
                    onPause={entry.job.status === "running" ? () => void pauseCatalogJob(entry.job.job_id) : undefined}
                    onResume={entry.job.status === "paused" ? () => void resumeCatalogJob(entry.job.job_id) : undefined}
                    onDismiss={
                      entry.job.status === "completed" || entry.job.status === "failed" || entry.job.status === "cancelled"
                        ? () => dismissCatalogJob(entry.job.job_id)
                        : undefined
                    }
                  />
                );
              case "relevance":
                return (
                  <RelevanceProgressPanel
                    key={entry.job.job_id}
                    job={entry.job}
                    onCancel={
                      entry.job.status === "queued" || entry.job.status === "running"
                        ? () => void cancelRelevanceJob(entry.job.job_id)
                        : undefined
                    }
                    onPause={entry.job.status === "running" ? () => void pauseRelevanceJob(entry.job.job_id) : undefined}
                    onResume={entry.job.status === "paused" ? () => void resumeRelevanceJob(entry.job.job_id) : undefined}
                    onDismiss={
                      entry.job.status === "completed" || entry.job.status === "failed" || entry.job.status === "cancelled"
                        ? () => dismissRelevanceJob(entry.job.job_id)
                        : undefined
                    }
                  />
                );
              case "v2":
                return (
                  <V2GenerationProgressPanel
                    key={entry.job.job_id}
                    job={entry.job}
                    onCancel={
                      entry.job.status === "queued" || entry.job.status === "running" || entry.job.status === "paused"
                        ? () => void cancelV2Job(entry.job.job_id)
                        : undefined
                    }
                    onPause={entry.job.status === "running" ? () => void pauseV2Job(entry.job.job_id) : undefined}
                    onResume={entry.job.status === "paused" ? () => void resumeV2Job(entry.job.job_id) : undefined}
                    onDismiss={
                      entry.job.status === "completed" || entry.job.status === "failed" || entry.job.status === "cancelled"
                        ? () => dismissV2Job(entry.job.job_id)
                        : undefined
                    }
                  />
                );
              default:
                return (
                  <CollectProgressPanel
                    key={entry.job.job_id}
                    job={entry.job}
                    onCancel={
                      entry.job.status === "queued" || entry.job.status === "running" || entry.job.status === "paused"
                        ? () => void cancelCollectJob(entry.job.job_id)
                        : undefined
                    }
                    onPause={entry.job.status === "running" ? () => void pauseCollectJob(entry.job.job_id) : undefined}
                    onResume={entry.job.status === "paused" ? () => void resumeCollectJob(entry.job.job_id) : undefined}
                    onDismiss={
                      entry.job.status === "completed" || entry.job.status === "failed" || entry.job.status === "cancelled"
                        ? () => dismissCollectJob(entry.job.job_id)
                        : undefined
                    }
                  />
                );
            }
          })}
        </div>
      </div> : (
        <div className="task-summary-rail" aria-label="작업 상태 요약">
          <span title={`실행 ${runningCount}`}>▶ {runningCount}</span>
          <span title={`일시정지 ${pausedCount}`}>Ⅱ {pausedCount}</span>
          <span title={`대기 ${queuedCount}`}>… {queuedCount}</span>
          <span className={failedCount > 0 ? "task-summary-rail--danger" : ""} title={`실패 ${failedCount}`}>! {failedCount}</span>
          {lastError ? <span className="task-summary-rail--danger" title="작업 오류">오류</span> : null}
          <span title={`완료 ${completedCount}`}>✓ {completedCount}</span>
        </div>
      )}
    </section>
  );
}
