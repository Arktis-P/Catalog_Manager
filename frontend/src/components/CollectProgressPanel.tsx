import type { CollectJob } from "../types";

interface CollectProgressPanelProps {
  job: CollectJob;
  onDismiss?: () => void;
}

function getProgressPercent(job: CollectJob): number | null {
  if (job.status === "completed") {
    return 100;
  }
  if ((job.phase === "counting" || job.phase === "saving") && job.total > 0) {
    return Math.min(100, Math.round((job.current / job.total) * 100));
  }
  return null;
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case "discovering":
      return "캐릭터 tag 발견";
    case "counting":
      return "post_count 조회";
    case "saving":
      return "DB 저장";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
    default:
      return "준비 중";
  }
}

export function CollectProgressPanel({ job, onDismiss }: CollectProgressPanelProps) {
  const percent = getProgressPercent(job);
  const isRunning = job.status === "queued" || job.status === "running";

  return (
    <div className={`progress-panel ${job.status === "failed" ? "progress-panel-error" : ""}`}>
      <div className="progress-panel-header">
        <strong>{job.series_tag || "Series"}</strong>
        <div className="card-actions">
          <span className="badge">{phaseLabel(job.phase)}</span>
          {onDismiss ? (
            <button className="btn btn-small" type="button" onClick={onDismiss}>
              Dismiss
            </button>
          ) : null}
        </div>
      </div>
      <p className="progress-panel-message">{job.message}</p>
      {isRunning ? (
        <div className={`progress-bar ${percent === null ? "progress-bar-indeterminate" : ""}`}>
          <div
            className="progress-bar-fill"
            style={percent === null ? undefined : { width: `${percent}%` }}
          />
        </div>
      ) : null}
      <div className="progress-panel-stats">
        {job.discovered > 0 ? <span>discovered {job.discovered}</span> : null}
        {job.created > 0 ? <span>added {job.created}</span> : null}
        {job.skipped_existing > 0 ? <span>skipped {job.skipped_existing}</span> : null}
        {job.phase === "counting" && job.total > 0 ? (
          <span>
            {job.current}/{job.total}
          </span>
        ) : null}
      </div>
      {job.error ? <div className="error-banner">{job.error}</div> : null}
    </div>
  );
}
