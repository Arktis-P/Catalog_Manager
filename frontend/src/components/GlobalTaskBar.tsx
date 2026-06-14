import { useMemo } from "react";
import { CollectProgressPanel } from "./CollectProgressPanel";
import { useCollectJobs } from "../context/CollectJobContext";
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
  const { jobs, dismissJob, lastError, clearLastError } = useCollectJobs();

  const activeJobs = useMemo(
    () =>
      jobs
        .filter(
          (job) =>
            job.status === "queued" ||
            job.status === "running" ||
            job.status === "completed" ||
            job.status === "failed",
        )
        .sort((a, b) => jobSortRank(a) - jobSortRank(b) || b.started_at.localeCompare(a.started_at)),
    [jobs],
  );

  if (activeJobs.length === 0 && !lastError) {
    return null;
  }

  return (
    <section className="global-task-bar" aria-label="Background tasks">
      <div className="global-task-bar-inner">
        {lastError ? (
          <div className="error-banner global-task-error">
            <span>{lastError}</span>
            <button className="btn btn-small" type="button" onClick={clearLastError}>
              Dismiss
            </button>
          </div>
        ) : null}
        {activeJobs.map((job) => (
          <CollectProgressPanel
            key={job.job_id}
            job={job}
            onDismiss={
              job.status === "completed" || job.status === "failed"
                ? () => dismissJob(job.job_id)
                : undefined
            }
          />
        ))}
      </div>
    </section>
  );
}
