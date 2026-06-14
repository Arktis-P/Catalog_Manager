import type { CollectJob } from "../types";

interface CollectProgressPanelProps {
  job: CollectJob;
  onDismiss?: () => void;
}

function getProgressPercent(job: CollectJob): number | null {
  if (job.status === "completed") {
    return 100;
  }
  if (job.total > 0) {
    return Math.min(100, Math.round((job.current / job.total) * 100));
  }
  return null;
}

function phaseLabel(phase: string): string {
  switch (phase) {
    case "discovering_pattern":
      return "패턴";
    case "discovering_posts_scan":
      return "tag";
    case "discovering_posts_verify":
      return "분류";
    case "discovering":
      return "발견";
    case "counting":
      return "count";
    case "extracting":
      return "외형";
    case "saving":
      return "저장";
    case "completed":
      return "완료";
    case "failed":
      return "실패";
    case "starting":
      return "시작";
    case "queued":
      return "대기";
    default:
      return "준비";
  }
}

function formatEta(job: CollectJob): string | null {
  if (job.job_type === "appearance_extract") {
    if (job.phase !== "extracting" || job.total <= 0 || job.current <= 0) {
      return null;
    }
    const remaining = job.total - job.current;
    const seconds = remaining * 0.5;
    if (seconds < 60) {
      return `~${Math.ceil(seconds)}s`;
    }
    return `~${Math.ceil(seconds / 60)}m`;
  }
  if (job.phase !== "counting" || job.total <= 0 || job.current <= 0) {
    return null;
  }
  const remaining = job.total - job.current;
  const seconds = remaining * 0.5;
  if (seconds < 60) {
    return `~${Math.ceil(seconds)}s`;
  }
  return `~${Math.ceil(seconds / 60)}m`;
}

function formatMeta(job: CollectJob, percent: number | null): string | null {
  const parts: string[] = [];
  if (job.job_type === "appearance_extract") {
    if (job.total > 0) {
      parts.push(`${job.current}/${job.total}${percent !== null ? ` ${percent}%` : ""}`);
    }
    if (job.status === "completed" && job.updated > 0) {
      parts.push(`updated ${job.updated}`);
    }
  } else if (job.total > 0) {
    parts.push(`${job.current}/${job.total}${percent !== null ? ` ${percent}%` : ""}`);
  } else if (job.discovered > 0) {
    parts.push(`discovered ${job.discovered}`);
  }
  const eta = formatEta(job);
  if (eta) {
    parts.push(eta);
  }
  if (job.status === "completed" && job.job_type === "character_collect") {
    parts.push(`+${job.created}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

function jobTypeLabel(job: CollectJob): string {
  return job.job_type === "appearance_extract" ? "Appearance" : "Collect";
}

export function CollectProgressPanel({ job, onDismiss }: CollectProgressPanelProps) {
  const percent = getProgressPercent(job);
  const isRunning = job.status === "queued" || job.status === "running";
  const meta = formatMeta(job, percent);

  return (
    <div
      className={`progress-panel progress-panel-compact${
        job.status === "failed" ? " progress-panel-error" : ""
      }${job.status === "completed" ? " progress-panel-done" : ""}`}
    >
      <div className="progress-panel-compact-row">
        <strong className="progress-panel-series" title={job.series_tag || "Series"}>
          {job.series_tag || "Series"}
        </strong>
        <span className="badge badge-compact badge-muted">{jobTypeLabel(job)}</span>
        <span className="badge badge-compact">{phaseLabel(job.phase)}</span>
        <span className="progress-panel-message-compact" title={job.message}>
          {job.message}
        </span>
        {isRunning ? (
          <div
            className={`progress-bar progress-bar-compact${
              percent === null ? " progress-bar-indeterminate" : ""
            }`}
          >
            <div
              className="progress-bar-fill"
              style={percent === null ? undefined : { width: `${percent}%` }}
            />
          </div>
        ) : null}
        {meta ? <span className="progress-panel-meta">{meta}</span> : null}
        {onDismiss ? (
          <button className="btn btn-small btn-ghost" type="button" onClick={onDismiss}>
            ×
          </button>
        ) : null}
      </div>
      {job.error ? <div className="progress-panel-error-line">{job.error}</div> : null}
    </div>
  );
}
