import { useMemo } from "react";
import { CollectProgressPanel } from "./CollectProgressPanel";
import { GenerationProgressPanel } from "./GenerationProgressPanel";
import { useCollectJobs } from "../context/CollectJobContext";
import { useGenerationJobs } from "../context/GenerationJobContext";
import type { CollectJob } from "../types";

function jobSortRank(job: CollectJob): number {
  if (job.status === "running") {
    return 0;
  }
  if (job.status === "queued") {
    return 1;
  }
  if (job.status === "failed") {
    return 2;
  }
  return 3;
}

export function GlobalTaskBar() {
  const { jobs: collectJobs, cancelJob: cancelCollectJob, dismissJob: dismissCollectJob, lastError: collectError, clearLastError: clearCollectError } =
    useCollectJobs();
  const {
    jobs: generationJobs,
    dismissJob: dismissGenerationJob,
    cancelJob,
    lastError: generationError,
    clearLastError: clearGenerationError,
  } = useGenerationJobs();

  const activeJobs = useMemo(
    () =>
      [...collectJobs, ...generationJobs]
        .filter(
          (job) =>
            job.status === "queued" ||
            job.status === "running" ||
            job.status === "completed" ||
            job.status === "failed" ||
            job.status === "cancelled",
        )
        .sort((a, b) => jobSortRank(a) - jobSortRank(b) || b.started_at.localeCompare(a.started_at)),
    [collectJobs, generationJobs],
  );

  const dismissibleJobs = useMemo(
    () => activeJobs.filter((job) => job.status === "completed" || job.status === "failed" || job.status === "cancelled"),
    [activeJobs],
  );

  const dismissAllCompleted = () => {
    for (const job of dismissibleJobs) {
      if (job.job_type === "image_generation") {
        dismissGenerationJob(job.job_id);
      } else {
        dismissCollectJob(job.job_id);
      }
    }
  };

  const lastError = collectError || generationError;

  if (activeJobs.length === 0 && !lastError) {
    return null;
  }

  return (
    <section className="global-task-bar" aria-label="Background tasks">
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
              }}
            >
              Dismiss
            </button>
          </div>
        ) : null}
        {activeJobs.length > 0 ? (
          <div className="global-task-bar-jobs">
            {dismissibleJobs.length > 0 ? (
              <div className="global-task-bar-actions">
                <button className="btn btn-small" type="button" onClick={dismissAllCompleted}>
                  완료된 작업 모두 지우기 ({dismissibleJobs.length})
                </button>
              </div>
            ) : null}
            {activeJobs.map((job) =>
              job.job_type === "image_generation" ? (
                <GenerationProgressPanel
                  key={job.job_id}
                  job={job}
                  onCancel={
                    job.status === "queued" || job.status === "running"
                      ? () => void cancelJob(job.job_id)
                      : undefined
                  }
                  onDismiss={
                    job.status === "completed" || job.status === "failed" || job.status === "cancelled"
                      ? () => dismissGenerationJob(job.job_id)
                      : undefined
                  }
                />
              ) : (
                <CollectProgressPanel
                  key={job.job_id}
                  job={job}
                  onCancel={job.status === "queued" || job.status === "running" ? () => void cancelCollectJob(job.job_id) : undefined}
                  onDismiss={
                    job.status === "completed" || job.status === "failed" || job.status === "cancelled"
                      ? () => dismissCollectJob(job.job_id)
                      : undefined
                  }
                />
              ),
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}
