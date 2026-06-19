import type { Series } from "../types";

function generationDepriorityRank(series: Series): number {
  if (series.generation_pipeline_done) {
    return 2;
  }
  if (series.status === "generated") {
    return 1;
  }
  return 0;
}

export function sortSeriesForGeneration(items: Series[]): Series[] {
  return [...items].sort((left, right) => {
    const leftDone = generationDepriorityRank(left);
    const rightDone = generationDepriorityRank(right);
    if (leftDone !== rightDone) {
      return leftDone - rightDone;
    }
    if (right.post_count !== left.post_count) {
      return right.post_count - left.post_count;
    }
    return left.series_tag.localeCompare(right.series_tag);
  });
}
