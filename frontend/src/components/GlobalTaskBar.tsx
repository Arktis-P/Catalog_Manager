import { CollectProgressPanel } from "./CollectProgressPanel";
import { useCollectJobs } from "../context/CollectJobContext";

export function GlobalTaskBar() {
  const { jobs, dismissJob, lastError, clearLastError } = useCollectJobs();
  const activeJobs = jobs.filter(
    (job) =>
      job.status === "queued" ||
      job.status === "running" ||
      job.status === "completed" ||
      job.status === "failed",
  );

  if (activeJobs.length === 0 && !lastError) {
    return null;
  }

  return (
    <section className="global-task-bar">
      <div className="global-task-bar-inner">
        <div className="global-task-bar-title">Background Tasks</div>
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
