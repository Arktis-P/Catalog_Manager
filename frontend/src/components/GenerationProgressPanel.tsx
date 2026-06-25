import type { CollectJob } from "../types";

interface GenerationProgressPanelProps {
  job: CollectJob;
  onDismiss?: () => void;
  onCancel?: () => void;
  onPause?: () => void;
  onResume?: () => void;
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

function pendingReviewImageUrl(imagePath: string | null | undefined): string | null {
  if (!imagePath) {
    return null;
  }
  const filename = imagePath.split(/[\\/]/).pop();
  return filename ? `/media/pending-review/${filename}` : null;
}

export function GenerationProgressPanel({ job, onDismiss, onCancel, onPause, onResume }: GenerationProgressPanelProps) {
  const percent = getProgressPercent(job);
  const isRunning = job.status === "queued" || job.status === "running";
  const isPaused = job.status === "paused";
  const previewUrl = pendingReviewImageUrl(job.last_image_path);
  const metaParts: string[] = [];
  if (job.total > 0) {
    metaParts.push(`${job.current}/${job.total}${percent !== null ? ` ${percent}%` : ""}`);
  }
  if (job.completed) {
    metaParts.push(`saved ${job.completed}`);
  }
  if (job.failed) {
    metaParts.push(`failed ${job.failed}`);
  }
  if (job.auto_pass || job.auto_warning || job.auto_reject) {
    metaParts.push(
      `auto pass ${job.auto_pass ?? 0} / warn ${job.auto_warning ?? 0} / reject ${job.auto_reject ?? 0}`,
    );
  }
  if (job.current_character_tag) {
    metaParts.push(job.current_character_tag);
  }

  return (
    <div
      className={`progress-panel progress-panel-compact generation-progress-panel${
        job.status === "failed" ? " progress-panel-error" : ""
      }${job.status === "completed" ? " progress-panel-done" : ""}${
        isPaused ? " progress-panel-paused" : ""
      }`}
    >
      <div className="progress-panel-compact-row">
        {isPaused ? (
          <span className="job-paused-indicator job-indicator-inline" aria-hidden="true" title="일시정지됨">⏸</span>
        ) : null}
        <strong className="progress-panel-series" title={job.series_tag || "Series"}>
          {job.series_tag || "Series"}
        </strong>
        <span className="badge badge-compact badge-muted">Generation</span>
        <span className="badge badge-compact">L{job.prompt_level ?? 1}</span>
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
        {metaParts.length > 0 ? <span className="progress-panel-meta">{metaParts.join(" · ")}</span> : null}
        {job.status === "queued" && onCancel ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="대기 취소"
            title="대기 취소"
            onClick={onCancel}
          >
            ×
          </button>
        ) : null}
        {job.status === "running" && onPause ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="일시정지"
            title="일시정지"
            onClick={onPause}
          >
            ⏸
          </button>
        ) : null}
        {job.status === "running" && onCancel ? (
          <button className="btn btn-small btn-ghost" type="button" onClick={onCancel}>
            Cancel
          </button>
        ) : null}
        {isPaused && onResume ? (
          <button
            className="btn btn-small btn-ghost"
            type="button"
            aria-label="재개"
            title="재개"
            onClick={onResume}
          >
            ▶ 재개
          </button>
        ) : null}
        {isPaused && onCancel ? (
          <button className="btn btn-small btn-ghost" type="button" onClick={onCancel}>
            ×
          </button>
        ) : null}
        {onDismiss ? (
          <button className="btn btn-small btn-ghost" type="button" onClick={onDismiss}>
            ×
          </button>
        ) : null}
      </div>
      {previewUrl ? (
        <div className="generation-preview-thumb">
          <img src={previewUrl} alt={job.current_character_tag || "generated preview"} />
        </div>
      ) : null}
      {job.error ? <div className="progress-panel-error-line">{job.error}</div> : null}
    </div>
  );
}
