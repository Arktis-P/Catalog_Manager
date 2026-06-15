import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { CollectJob } from "../types";
import { ensureNotificationPermission, showTaskCompleteNotification } from "../utils/notifications";

interface GenerationJobContextValue {
  jobs: CollectJob[];
  startGeneration: (
    seriesId: number,
    payload?: { character_ids?: number[]; prompt_level?: number; require_confirmed?: boolean },
  ) => Promise<CollectJob>;
  cancelJob: (jobId: string) => Promise<void>;
  dismissJob: (jobId: string) => void;
  isGeneratingSeries: (seriesId: number) => boolean;
  lastError: string | null;
  clearLastError: () => void;
}

const GenerationJobContext = createContext<GenerationJobContextValue | null>(null);

function upsertJob(jobs: CollectJob[], nextJob: CollectJob): CollectJob[] {
  const index = jobs.findIndex((job) => job.job_id === nextJob.job_id);
  if (index === -1) {
    return [nextJob, ...jobs];
  }
  const copy = [...jobs];
  copy[index] = nextJob;
  return copy;
}

function normalizeGenerationJob(job: CollectJob): CollectJob {
  return {
    ...job,
    job_type: "image_generation",
    discovered: job.discovered ?? 0,
    created: job.created ?? job.completed ?? 0,
    skipped_existing: job.skipped_existing ?? 0,
    updated: job.updated ?? 0,
  };
}

export function GenerationJobProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<CollectJob[]>([]);
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(() => new Set());
  const [lastError, setLastError] = useState<string | null>(null);
  const notifiedJobIdsRef = useRef<Set<string>>(new Set());

  const visibleJobs = useMemo(
    () => jobs.filter((job) => !dismissedJobIds.has(job.job_id)),
    [jobs, dismissedJobIds],
  );

  const runningJobIds = useMemo(
    () =>
      visibleJobs
        .filter((job) => job.status === "queued" || job.status === "running")
        .map((job) => job.job_id),
    [visibleJobs],
  );

  useEffect(() => {
    void ensureNotificationPermission();
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const response = await api.listGenerationJobs();
      setJobs((current) => {
        let merged = current;
        for (const job of response.items.map(normalizeGenerationJob)) {
          merged = upsertJob(merged, job);
        }
        return merged;
      });
    } catch {
      // ignore polling bootstrap errors
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (runningJobIds.length === 0) {
      return;
    }

    const poll = async () => {
      try {
        const updates = await Promise.all(runningJobIds.map((jobId) => api.getGenerationJob(jobId)));
        setJobs((current) => {
          let merged = current;
          for (const job of updates.map(normalizeGenerationJob)) {
            const prior = current.find((item) => item.job_id === job.job_id);
            if (
              prior &&
              prior.status !== job.status &&
              job.status === "completed" &&
              !notifiedJobIdsRef.current.has(job.job_id)
            ) {
              notifiedJobIdsRef.current.add(job.job_id);
              showTaskCompleteNotification(
                `${job.series_tag} 이미지 생성 완료`,
                `${job.completed ?? 0}장 저장 · 실패 ${job.failed ?? 0}`,
              );
            }
            if (
              prior &&
              prior.status !== job.status &&
              job.status === "failed" &&
              !notifiedJobIdsRef.current.has(job.job_id)
            ) {
              notifiedJobIdsRef.current.add(job.job_id);
              showTaskCompleteNotification(
                `${job.series_tag} 이미지 생성 실패`,
                job.error || job.message,
              );
            }
            merged = upsertJob(merged, job);
          }
          return merged;
        });
      } catch (err) {
        setLastError(err instanceof Error ? err.message : "Failed to poll generation jobs");
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [runningJobIds.join("|")]);

  const registerStartedJob = useCallback((job: CollectJob) => {
    setDismissedJobIds((current) => {
      if (!current.has(job.job_id)) {
        return current;
      }
      const next = new Set(current);
      next.delete(job.job_id);
      return next;
    });
    setJobs((current) => upsertJob(current, normalizeGenerationJob(job)));
  }, []);

  const startGeneration = useCallback(
    async (
      seriesId: number,
      payload: { character_ids?: number[]; prompt_level?: number; require_confirmed?: boolean } = {},
    ) => {
      setLastError(null);
      const job = normalizeGenerationJob(await api.startGenerationJob(seriesId, payload));
      registerStartedJob(job);
      return job;
    },
    [registerStartedJob],
  );

  const cancelJob = useCallback(async (jobId: string) => {
    const job = normalizeGenerationJob(await api.cancelGenerationJob(jobId));
    setJobs((current) => upsertJob(current, job));
  }, []);

  const dismissJob = useCallback((jobId: string) => {
    setDismissedJobIds((current) => new Set(current).add(jobId));
  }, []);

  const isGeneratingSeries = useCallback(
    (seriesId: number) =>
      visibleJobs.some(
        (job) =>
          job.series_id === seriesId &&
          job.job_type === "image_generation" &&
          (job.status === "queued" || job.status === "running"),
      ),
    [visibleJobs],
  );

  const value = useMemo(
    () => ({
      jobs: visibleJobs,
      startGeneration,
      cancelJob,
      dismissJob,
      isGeneratingSeries,
      lastError,
      clearLastError: () => setLastError(null),
    }),
    [visibleJobs, startGeneration, cancelJob, dismissJob, isGeneratingSeries, lastError],
  );

  return <GenerationJobContext.Provider value={value}>{children}</GenerationJobContext.Provider>;
}

export function useGenerationJobs() {
  const context = useContext(GenerationJobContext);
  if (!context) {
    throw new Error("useGenerationJobs must be used within GenerationJobProvider");
  }
  return context;
}
