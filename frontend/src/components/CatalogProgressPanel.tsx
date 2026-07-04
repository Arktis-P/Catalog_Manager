import type { CatalogJob } from "../types";

interface CatalogProgressPanelProps {
  job: CatalogJob;
  onDismiss?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
}

function getProgressPercent(job: CatalogJob): number | null {
  if (job.status === "completed") return 100;
  if (job.total > 0) return Math.min(100, Math.round((job.current / job.total) * 100));
  return null;
}

function jobTypeLabel(job: CatalogJob): string {
  return job.job_type === "character_catalog_list" ? "캐릭터 목록 수집" : "통합 태그 수집";
}

function statusShortLabel(status: string): string {
  switch (status) {
    case "queued": return "대기";
    case "running": return "진행";
    case "paused": return "정지";
    case "completed": return "완료";
    case "failed": return "실패";
    case "cancelled": return "취소";
    default: return status;
  }
}

export function CatalogProgressPanel({ job, onDismiss, onCancel, onPause, onResume }: CatalogProgressPanelProps) {
  const percent = getProgressPercent(job);
  const isActive = job.status === "running" || job.status === "paused";
  const isDone = job.status === "completed" || job.status === "failed" || job.status === "cancelled";

  const metaParts: string[] = [];
  if (job.job_type === "character_catalog_tags") {
    if (job.total > 0) metaParts.push(`${job.current}/${job.total}`);
    metaParts.push(`성공 ${job.success_count} · 부분 ${job.partial_count} · 실패 ${job.failed_count}`);
  } else {
    metaParts.push(`신규 ${job.created} · 갱신 ${job.updated}`);
  }

  const displayName = job.current_character_tag || jobTypeLabel(job);

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
        <span className="badge badge-compact badge-muted task-badge">{jobTypeLabel(job)}</span>
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

      {isActive && job.active_items.length > 0 ? (
        <ul className="task-active-items">
          {job.active_items.map((tag) => (
            <li key={tag} className="task-active-item">
              <span className="job-running-indicator task-dot" aria-hidden="true" />
              {tag}
            </li>
          ))}
        </ul>
      ) : null}

      {job.error ? <div className="progress-panel-error-line task-error-line">{job.error}</div> : null}
    </div>
  );
}
