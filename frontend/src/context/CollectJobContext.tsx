import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api/client";
import type { CollectJob } from "../types";

interface CollectJobContextValue {
  jobs: CollectJob[];
  startCollect: (seriesId: number) => Promise<CollectJob>;
  dismissJob: (jobId: string) => void;
  isCollectingSeries: (seriesId: number) => boolean;
  lastError: string | null;
  clearLastError: () => void;
}

const CollectJobContext = createContext<CollectJobContextValue | null>(null);

function upsertJob(jobs: CollectJob[], nextJob: CollectJob): CollectJob[] {
  const index = jobs.findIndex((job) => job.job_id === nextJob.job_id);
  if (index === -1) {
    return [nextJob, ...jobs];
  }
  const copy = [...jobs];
  copy[index] = nextJob;
  return copy;
}

export function CollectJobProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<CollectJob[]>([]);
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(() => new Set());
  const [lastError, setLastError] = useState<string | null>(null);

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

  const refreshJobs = useCallback(async () => {
    try {
      const response = await api.listCollectJobs();
      setJobs((current) => {
        let merged = current;
        for (const job of response.items) {
          merged = upsertJob(merged, job);
        }
        return merged;
      });
    } catch {
      // Ignore refresh errors during polling; pages can still start jobs.
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
        const updates = await Promise.all(runningJobIds.map((jobId) => api.getCollectJob(jobId)));
        setJobs((current) => {
          let merged = current;
          for (const job of updates) {
            merged = upsertJob(merged, job);
          }
          return merged;
        });
      } catch (err) {
        setLastError(err instanceof Error ? err.message : "Failed to poll collect progress");
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 800);
    return () => window.clearInterval(timer);
  }, [runningJobIds.join("|")]);

  const startCollect = useCallback(async (seriesId: number) => {
    setLastError(null);
    const job = await api.startCollectCharactersJob(seriesId);
    setDismissedJobIds((current) => {
      if (!current.has(job.job_id)) {
        return current;
      }
      const next = new Set(current);
      next.delete(job.job_id);
      return next;
    });
    setJobs((current) => upsertJob(current, job));
    return job;
  }, []);

  const dismissJob = useCallback((jobId: string) => {
    setDismissedJobIds((current) => new Set(current).add(jobId));
  }, []);

  const isCollectingSeries = useCallback(
    (seriesId: number) =>
      visibleJobs.some(
        (job) =>
          job.series_id === seriesId && (job.status === "queued" || job.status === "running"),
      ),
    [visibleJobs],
  );

  const value = useMemo(
    () => ({
      jobs: visibleJobs,
      startCollect,
      dismissJob,
      isCollectingSeries,
      lastError,
      clearLastError: () => setLastError(null),
    }),
    [visibleJobs, startCollect, dismissJob, isCollectingSeries, lastError],
  );

  return <CollectJobContext.Provider value={value}>{children}</CollectJobContext.Provider>;
}

export function useCollectJobs() {
  const context = useContext(CollectJobContext);
  if (!context) {
    throw new Error("useCollectJobs must be used within CollectJobProvider");
  }
  return context;
}
