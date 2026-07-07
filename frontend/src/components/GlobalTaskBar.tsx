import { useMemo } from "react";
import { CatalogProgressPanel } from "./CatalogProgressPanel";
import { CollectProgressPanel } from "./CollectProgressPanel";
import { GenerationProgressPanel } from "./GenerationProgressPanel";
import { ReviewRegenerateProgressPanel } from "./ReviewRegenerateProgressPanel";
import { useCharacterCatalogJobs } from "../context/CharacterCatalogJobContext";
import { useCollectJobs } from "../context/CollectJobContext";
import { useGenerationJobs } from "../context/GenerationJobContext";
import { useReviewRegenerateJobs } from "../context/ReviewRegenerateContext";
import type { CatalogJob, CollectJob, ReviewRegenerateJob } from "../types";

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

export function GlobalTaskBar() {
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
  } = useGenerationJobs();
  const {
    jobs: catalogJobs,
    cancelJob: cancelCatalogJob,
    pauseJob: pauseCatalogJob,
    resumeJob: resumeCatalogJob,
    dismissJob: dismissCatalogJob,
    lastError: catalogError,
    clearLastError: clearCatalogError,
  } = useCharacterCatalogJobs();
  const { jobs: regenerateJobs } = useReviewRegenerateJobs();

  const isCatalogJob = (job: CollectJob | CatalogJob | (typeof generationJobs)[number]): job is CatalogJob =>
    job.job_type === "character_catalog_list" || job.job_type === "character_catalog_tags";

  const isRegenerateJob = (
    job: CollectJob | CatalogJob | ReviewRegenerateJob | (typeof generationJobs)[number],
  ): job is ReviewRegenerateJob => "job_id" in job && !("job_type" in job);

  const activeJobs = useMemo(
    () =>
      [...collectJobs, ...generationJobs, ...catalogJobs, ...regenerateJobs]
        .filter(
          (job) =>
            job.status === "queued" ||
            job.status === "running" ||
            job.status === "paused" ||
            job.status === "completed" ||
            job.status === "failed" ||
            job.status === "cancelled",
        )
        .sort((a, b) => jobSortRank(a) - jobSortRank(b) || b.started_at.localeCompare(a.started_at)),
    [collectJobs, generationJobs, catalogJobs, regenerateJobs],
  );

  const dismissibleJobs = useMemo(
    () => activeJobs.filter((job) => job.status === "completed" || job.status === "failed" || job.status === "cancelled"),
    [activeJobs],
  );

  const dismissAllCompleted = () => {
    for (const job of dismissibleJobs) {
      if (isRegenerateJob(job)) {
        continue;
      } else if (job.job_type === "image_generation") {
        dismissGenerationJob(job.job_id);
      } else if (isCatalogJob(job)) {
        dismissCatalogJob(job.job_id);
      } else {
        dismissCollectJob(job.job_id);
      }
    }
  };

  const lastError = collectError || generationError || catalogError;

  const queuedCount = useMemo(
    () => activeJobs.filter((j) => j.status === "queued").length,
    [activeJobs],
  );

  if (activeJobs.length === 0 && !lastError) {
    return null;
  }

  return (
    <section className="global-task-bar" aria-label="Background tasks">
      {/* 고정 헤더: 항상 보임 */}
      <div className="task-summary-bar">
        <span className="task-summary-count">
          대기 {queuedCount} / 전체 {activeJobs.length}
        </span>
        {dismissibleJobs.length > 0 ? (
          <button className="btn btn-small" type="button" onClick={dismissAllCompleted}>
            완료 지우기 ({dismissibleJobs.length})
          </button>
        ) : null}
      </div>

      {/* 스크롤 영역: 작업 목록 */}
      <div className="global-task-bar-inner">
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
          {activeJobs.map((job) =>
            isRegenerateJob(job) ? (
              <ReviewRegenerateProgressPanel key={job.job_id} job={job} />
            ) : job.job_type === "image_generation" ? (
              <GenerationProgressPanel
                key={job.job_id}
                job={job}
                onCancel={
                  job.status === "queued" || job.status === "running" || job.status === "paused"
                    ? () => void cancelJob(job.job_id)
                    : undefined
                }
                onPause={job.status === "running" ? () => void pauseGenerationJob(job.job_id) : undefined}
                onResume={job.status === "paused" ? () => void resumeGenerationJob(job.job_id) : undefined}
                onDismiss={
                  job.status === "completed" || job.status === "failed" || job.status === "cancelled"
                    ? () => dismissGenerationJob(job.job_id)
                    : undefined
                }
              />
            ) : isCatalogJob(job) ? (
              <CatalogProgressPanel
                key={job.job_id}
                job={job}
                onCancel={
                  job.status === "queued" || job.status === "running" || job.status === "paused"
                    ? () => void cancelCatalogJob(job.job_id)
                    : undefined
                }
                onPause={job.status === "running" ? () => void pauseCatalogJob(job.job_id) : undefined}
                onResume={job.status === "paused" ? () => void resumeCatalogJob(job.job_id) : undefined}
                onDismiss={
                  job.status === "completed" || job.status === "failed" || job.status === "cancelled"
                    ? () => dismissCatalogJob(job.job_id)
                    : undefined
                }
              />
            ) : (
              <CollectProgressPanel
                key={job.job_id}
                job={job}
                onCancel={
                  job.status === "queued" || job.status === "running" || job.status === "paused"
                    ? () => void cancelCollectJob(job.job_id)
                    : undefined
                }
                onPause={job.status === "running" ? () => void pauseCollectJob(job.job_id) : undefined}
                onResume={job.status === "paused" ? () => void resumeCollectJob(job.job_id) : undefined}
                onDismiss={
                  job.status === "completed" || job.status === "failed" || job.status === "cancelled"
                    ? () => dismissCollectJob(job.job_id)
                    : undefined
                }
              />
            ),
          )}
        </div>
      </div>
    </section>
  );
}
