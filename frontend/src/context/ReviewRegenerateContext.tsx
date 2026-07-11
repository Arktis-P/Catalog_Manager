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
import type { ReviewRegenerateJob } from "../types";

interface ReviewRegenerateContextValue {
  jobs: ReviewRegenerateJob[];
  enqueueRegenerate: (
    characterId: number,
    payload: { prompt: string; gender?: string | null },
  ) => Promise<ReviewRegenerateJob>;
  enqueueRegenerateGlobal: (
    globalCharacterId: number,
    payload: { prompt: string; gender?: string | null },
  ) => Promise<ReviewRegenerateJob>;
  isCharacterRegenerating: (characterId: number, scope?: string) => boolean;
  getCharacterJob: (characterId: number, scope?: string) => ReviewRegenerateJob | null;
  dismissJob: (jobId: string) => void;
  lastError: string | null;
  clearLastError: () => void;
  lastCompletedJob: ReviewRegenerateJob | null;
  clearLastCompletedJob: () => void;
}

const ReviewRegenerateContext = createContext<ReviewRegenerateContextValue | null>(null);

function upsertJob(jobs: ReviewRegenerateJob[], nextJob: ReviewRegenerateJob): ReviewRegenerateJob[] {
  const index = jobs.findIndex((job) => job.job_id === nextJob.job_id);
  if (index === -1) {
    return [nextJob, ...jobs];
  }
  const copy = [...jobs];
  copy[index] = nextJob;
  return copy;
}

export function ReviewRegenerateProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<ReviewRegenerateJob[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastCompletedJob, setLastCompletedJob] = useState<ReviewRegenerateJob | null>(null);
  const notifiedJobIdsRef = useRef<Set<string>>(new Set());

  const runningJobIds = useMemo(
    () =>
      jobs
        .filter((job) => job.status === "queued" || job.status === "running")
        .map((job) => job.job_id),
    [jobs],
  );

  const handleJobUpdates = useCallback((updates: ReviewRegenerateJob[], previous: ReviewRegenerateJob[]) => {
    for (const job of updates) {
      const prior = previous.find((item) => item.job_id === job.job_id);
      if (!prior || prior.status === job.status) {
        continue;
      }
      if (job.status === "completed" && !notifiedJobIdsRef.current.has(job.job_id)) {
        notifiedJobIdsRef.current.add(job.job_id);
        setLastCompletedJob(job);
      }
      if (job.status === "failed" && !notifiedJobIdsRef.current.has(`failed:${job.job_id}`)) {
        notifiedJobIdsRef.current.add(`failed:${job.job_id}`);
        setLastError(job.error || `${job.character_tag} 재생성 실패`);
      }
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const response = await api.listReviewRegenerateJobs();
      setJobs((current) => {
        let merged = current;
        for (const job of response.items) {
          merged = upsertJob(merged, job);
        }
        handleJobUpdates(response.items, current);
        return merged;
      });
    } catch {
      // Ignore refresh errors during polling.
    }
  }, [handleJobUpdates]);

  useEffect(() => {
    void refreshJobs();
  }, [refreshJobs]);

  useEffect(() => {
    if (runningJobIds.length === 0) {
      return;
    }

    const poll = async () => {
      try {
        const updates = await Promise.all(runningJobIds.map((jobId) => api.getReviewRegenerateJob(jobId)));
        setJobs((current) => {
          handleJobUpdates(updates, current);
          let merged = current;
          for (const job of updates) {
            merged = upsertJob(merged, job);
          }
          return merged;
        });
      } catch (err) {
        setLastError(err instanceof Error ? err.message : "재생성 작업 상태를 불러오지 못했습니다.");
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 800);
    return () => window.clearInterval(timer);
  }, [runningJobIds.join("|"), handleJobUpdates]);

  const registerStartedJob = useCallback((job: ReviewRegenerateJob) => {
    setJobs((current) => upsertJob(current, job));
  }, []);

  const enqueueRegenerate = useCallback(
    async (characterId: number, payload: { prompt: string; gender?: string | null }) => {
      setLastError(null);
      const job = await api.regenerateCatalogCharacter(characterId, payload);
      registerStartedJob(job);
      return job;
    },
    [registerStartedJob],
  );

  const enqueueRegenerateGlobal = useCallback(
    async (globalCharacterId: number, payload: { prompt: string; gender?: string | null }) => {
      setLastError(null);
      const job = await api.regenerateGlobalCatalogCharacter(globalCharacterId, payload);
      registerStartedJob(job);
      return job;
    },
    [registerStartedJob],
  );

  const isCharacterRegenerating = useCallback(
    (characterId: number, scope: string = "series") =>
      jobs.some(
        (job) =>
          job.character_id === characterId &&
          job.scope === scope &&
          (job.status === "queued" || job.status === "running"),
      ),
    [jobs],
  );

  const getCharacterJob = useCallback(
    (characterId: number, scope: string = "series") =>
      jobs.find(
        (job) =>
          job.character_id === characterId &&
          job.scope === scope &&
          (job.status === "queued" || job.status === "running"),
      ) ?? null,
    [jobs],
  );

  const dismissJob = useCallback((jobId: string) => {
    setJobs((current) => current.filter((job) => job.job_id !== jobId));
    void api.dismissReviewRegenerateJob(jobId).catch(() => {
      // Ignore dismiss errors; job will simply reappear on next refresh if it failed server-side.
    });
  }, []);

  const value = useMemo(
    () => ({
      jobs,
      enqueueRegenerate,
      enqueueRegenerateGlobal,
      isCharacterRegenerating,
      getCharacterJob,
      dismissJob,
      lastError,
      clearLastError: () => setLastError(null),
      lastCompletedJob,
      clearLastCompletedJob: () => setLastCompletedJob(null),
    }),
    [
      jobs,
      enqueueRegenerate,
      enqueueRegenerateGlobal,
      isCharacterRegenerating,
      getCharacterJob,
      dismissJob,
      lastError,
      lastCompletedJob,
    ],
  );

  return <ReviewRegenerateContext.Provider value={value}>{children}</ReviewRegenerateContext.Provider>;
}

export function useReviewRegenerateJobs() {
  const context = useContext(ReviewRegenerateContext);
  if (!context) {
    throw new Error("useReviewRegenerateJobs must be used within ReviewRegenerateProvider");
  }
  return context;
}
