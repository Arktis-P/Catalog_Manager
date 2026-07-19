import type { V2GenerationJobState } from "../types";

interface V2GenerationProgressPanelProps {
  job: V2GenerationJobState;
  onDismiss?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}

function getProgressPercent(job: V2GenerationJobState): number | null {
  if (job.status === "completed") return 100;
  if (job.total > 0) return Math.min(100, Math.round((job.current / job.total) * 100));
  return null;
}

function statusShortLabel(status: string): string {
  switch (status) {
    case "queued": return "대기";
    case "running": return "진행";
    case "completed": return "완료";
    case "failed": return "실패";
    case "cancelled": return "취소";
    case "paused": return "정지";
    default: return status;
  }
}

export function V2GenerationProgressPanel({ job, onDismiss, onCancel, onPause, onResume }: V2GenerationProgressPanelProps) {
  const percent = getProgressPercent(job);
  const isActive = job.status === "running" || job.status === "paused";
  const isDone = job.status === "completed" || job.status === "failed" || job.status === "cancelled";

  const metaParts: string[] = [];
  if (job.total > 0) metaParts.push(`${job.current}/${job.total}`);
  metaParts.push(`완료 ${job.completed} · 실패 ${job.failed}`);

  const displayName = job.current_character_tag || "V2 이미지 생성";

  return (
    <div
      className={`task-card${job.status === "failed" ? " task-card-error" : ""}${isDone ? " task-card-done" : ""}${job.status === "paused" ? " task-card-paused" : ""}`}
    >
      <div className="task-row1">
        {job.status === "running" ? (
          <span className="job-running-indicator task-dot" aria-hidden="true" />
        ) : job.status === "paused" ? (
          <span className="task-dot task-dot-paused" aria-hidden="true">⏸</span>
        ) : null}
        <strong className="task-name" title={displayName}>{displayName}</strong>
        <span className="badge badge-compact badge-muted task-badge">V2 생성</span>
        <span className="badge badge-compact">{statusShortLabel(job.status)}</span>
        {metaParts.length > 0 ? <span className="task-meta">{metaParts.join(" · ")}</span> : null}
        <div className="task-row1-spacer" />
        {job.status === "running" && onPause ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="일시정지" title="일시정지" onClick={onPause}>⏸</button>
        ) : null}
        {job.status === "paused" && onResume ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="재개" title="재개" onClick={onResume}>▶</button>
        ) : null}
        {isDone && onDismiss ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="닫기" onClick={onDismiss}>×</button>
        ) : null}
        {!isDone && onCancel ? (
          <button className="btn btn-small btn-ghost task-btn" type="button" aria-label="취소" onClick={onCancel}>×</button>
        ) : null}
      </div>

      {isActive ? (
        <div className="task-row2">
          <span className="task-msg" title={job.message}>{job.message || ""}</span>
          <div className={`task-bar${percent === null ? " task-bar-indeterminate" : ""}`}>
            <div className="task-bar-fill" style={percent !== null ? { width: `${percent}%` } : undefined} />
          </div>
        </div>
      ) : null}

      {job.last_failure_reason ? (
        <div className="progress-panel-error-line task-error-line">{job.last_failure_reason}</div>
      ) : null}
    </div>
  );
}
