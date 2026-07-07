import type { ReviewRegenerateJob } from "../types";

interface ReviewRegenerateProgressPanelProps {
  job: ReviewRegenerateJob;
}

function statusLabel(status: string): string {
  switch (status) {
    case "queued":
      return "대기";
    case "running":
      return "재생성 중";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
    default:
      return status;
  }
}

export function ReviewRegenerateProgressPanel({ job }: ReviewRegenerateProgressPanelProps) {
  const isActive = job.status === "queued" || job.status === "running";
  const percent = job.total > 0 ? Math.min(100, Math.round((job.current / job.total) * 100)) : null;

  return (
    <div
      className={`task-card${job.status === "failed" ? " task-card-error" : ""}${
        job.status === "completed" ? " task-card-done" : ""
      }`}
    >
      <div className="task-row1">
        {job.status === "running" ? <span className="job-running-indicator task-dot" aria-hidden="true" /> : null}
        <strong className="task-name" title={job.character_tag}>
          {job.character_tag || "—"}
        </strong>
        <span className="badge badge-compact badge-muted task-badge">재생성</span>
        <span className="badge badge-compact">{statusLabel(job.status)}</span>
        {percent !== null && isActive ? <span className="task-meta">{percent}%</span> : null}
      </div>
      {isActive ? (
        <div className="task-row2">
          <span className="task-msg" title={job.message}>
            {job.message || ""}
          </span>
          <div className={`task-bar${percent === null ? " task-bar-indeterminate" : ""}`}>
            <div className="task-bar-fill" style={percent !== null ? { width: `${percent}%` } : undefined} />
          </div>
        </div>
      ) : null}
      {job.error ? <div className="progress-panel-error-line task-error-line">{job.error}</div> : null}
    </div>
  );
}
