import type { Series } from "../types";

const WORKFLOW_STATUSES = new Set([
  "disabled",
  "completed",
  "reviewing",
  "generating",
  "generated",
]);

export type SeriesStatusTone = "success" | "warning" | "muted";

export function resolveSeriesStatus(series: Series): { label: string; tone: SeriesStatusTone } {
  const status = series.status;

  if (WORKFLOW_STATUSES.has(status)) {
    return {
      label: status,
      tone:
        status === "completed" || status === "generated"
          ? "success"
          : status === "generating"
            ? "warning"
            : "muted",
    };
  }

  if (
    series.all_appearance_collected ||
    status === "tagged" ||
    status === "all_collected"
  ) {
    return { label: "tagged", tone: "success" };
  }

  if (status === "collecting") {
    return { label: "collecting", tone: "warning" };
  }

  if (status === "collected" || series.character_count > 0) {
    return { label: "collected", tone: "success" };
  }

  return { label: status || "pending", tone: "muted" };
}

export function seriesStatusBadgeClass(tone: SeriesStatusTone): string {
  if (tone === "success") {
    return "badge badge-success";
  }
  if (tone === "warning") {
    return "badge badge-warning";
  }
  return "badge";
}
