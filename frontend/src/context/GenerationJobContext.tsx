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
import type { CollectJob, V2GenerationJobState, V2GenerationStartPayload } from "../types";
import { useNotificationMode } from "./NotificationModeContext";
import { ensureNotificationPermission, showTaskCompleteNotification } from "../utils/notifications";

interface GenerationJobContextValue {
  jobs: CollectJob[];
  startGeneration: (
    seriesId: number,
    payload?: { character_ids?: number[]; prompt_level?: number; require_confirmed?: boolean },
  ) => Promise<CollectJob>;
  startCharacterGeneration: (characterIds: number[], promptLevel?: number) => Promise<CollectJob>;
  cancelJob: (jobId: string) => Promise<void>;
  pauseJob: (jobId: string) => Promise<void>;
  resumeJob: (jobId: string) => Promise<void>;
  dismissJob: (jobId: string) => void;
  isGeneratingSeries: (seriesId: number) => boolean;
  isGeneratingCharacters: () => boolean;
  lastError: string | null;
  clearLastError: () => void;
  v2Jobs: V2GenerationJobState[];
  startV2Generation: (payload: V2GenerationStartPayload) => Promise<V2GenerationJobState>;
  cancelV2Job: (jobId: string) => Promise<void>;
  dismissV2Job: (jobId: string) => void;
  isV2GenerationActive: () => boolean;
}

const GenerationJobContext = createContext<GenerationJobContextValue | null>(null);

function upsertJob<T extends { job_id: string }>(jobs: T[], nextJob: T): T[] {
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
  const [v2Jobs, setV2Jobs] = useState<V2GenerationJobState[]>([]);
  const [dismissedV2JobIds, setDismissedV2JobIds] = useState<Set<string>>(() => new Set());
  const [lastError, setLastError] = useState<string | null>(null);
  const notifiedJobIdsRef = useRef<Set<string>>(new Set());
  const { mode: notificationMode } = useNotificationMode();
  const notificationModeRef = useRef(notificationMode);
  notificationModeRef.current = notificationMode;
  const allDoneCountRef = useRef(0);
  const prevRunningCountRef = useRef(0);
  const pollFailCountRef = useRef(0);
  const POLL_ERROR_THRESHOLD = 3;

  const visibleJobs = useMemo(
    () => jobs.filter((job) => !dismissedJobIds.has(job.job_id)),
    [jobs, dismissedJobIds],
  );

  const runningJobIds = useMemo(
    () =>
      visibleJobs
        .filter((job) => job.status === "queued" || job.status === "running" || job.status === "paused")
        .map((job) => job.job_id),
    [visibleJobs],
  );

  const visibleV2Jobs = useMemo(
    () => v2Jobs.filter((job) => !dismissedV2JobIds.has(job.job_id)),
    [v2Jobs, dismissedV2JobIds],
  );

  const runningV2JobIds = useMemo(
    () =>
      visibleV2Jobs
        .filter((job) => job.status === "queued" || job.status === "running")
        .map((job) => job.job_id),
    [visibleV2Jobs],
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

  // "모든 작업 완료 시 알림" 모드: running → idle 전환 감지
  useEffect(() => {
    const wasRunning = prevRunningCountRef.current > 0;
    prevRunningCountRef.current = runningJobIds.length;
    if (wasRunning && runningJobIds.length === 0 && notificationMode === "all_done") {
      const count = allDoneCountRef.current;
      allDoneCountRef.current = 0;
      if (count > 0) {
        showTaskCompleteNotification("모든 이미지 생성 완료", `${count}개 작업 완료`);
      }
    }
  }, [runningJobIds.length, notificationMode]);

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
              const mode = notificationModeRef.current;
              if (mode === "each") {
                showTaskCompleteNotification(
                  `${job.series_tag} 이미지 생성 완료`,
                  `${job.completed ?? 0}장 저장 · 실패 ${job.failed ?? 0}`,
                );
              } else if (mode === "all_done") {
                allDoneCountRef.current++;
              }
            }
            if (
              prior &&
              prior.status !== job.status &&
              job.status === "failed" &&
              !notifiedJobIdsRef.current.has(job.job_id)
            ) {
              notifiedJobIdsRef.current.add(job.job_id);
              const mode = notificationModeRef.current;
              if (mode === "each") {
                showTaskCompleteNotification(
                  `${job.series_tag} 이미지 생성 실패`,
                  job.error || job.message,
                );
              }
            }
            merged = upsertJob(merged, job);
          }
          return merged;
        });
        pollFailCountRef.current = 0;
        setLastError(null);
      } catch (err) {
        pollFailCountRef.current += 1;
        if (pollFailCountRef.current >= POLL_ERROR_THRESHOLD) {
          setLastError(err instanceof Error ? err.message : "Failed to poll generation jobs");
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [runningJobIds.join("|")]);

  useEffect(() => {
    if (runningV2JobIds.length === 0) {
      return;
    }
    const poll = async () => {
      try {
        const updates = await Promise.all(runningV2JobIds.map((jobId) => api.getV2GenerationJob(jobId)));
        setV2Jobs((current) => {
          let merged = current;
          for (const job of updates) {
            merged = upsertJob(merged, job);
          }
          return merged;
        });
      } catch {
        // Ignore transient poll errors.
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1000);
    return () => window.clearInterval(timer);
  }, [runningV2JobIds.join("|")]);

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

  const startCharacterGeneration = useCallback(
    async (characterIds: number[], promptLevel = 1) => {
      setLastError(null);
      const job = normalizeGenerationJob(
        await api.startCharacterGenerationJob({ character_ids: characterIds, prompt_level: promptLevel }),
      );
      registerStartedJob(job);
      return job;
    },
    [registerStartedJob],
  );

  const cancelJob = useCallback(async (jobId: string) => {
    const job = normalizeGenerationJob(await api.cancelGenerationJob(jobId));
    setJobs((current) => upsertJob(current, job));
  }, []);

  const pauseJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = normalizeGenerationJob(await api.pauseGenerationJob(jobId));
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to pause job");
    }
  }, []);

  const resumeJob = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = normalizeGenerationJob(await api.resumeGenerationJob(jobId));
      setJobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to resume job");
    }
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
          (job.status === "queued" || job.status === "running" || job.status === "paused"),
      ),
    [visibleJobs],
  );

  const isGeneratingCharacters = useCallback(
    () =>
      visibleJobs.some(
        (job) =>
          job.series_id === 0 &&
          job.job_type === "image_generation" &&
          (job.status === "queued" || job.status === "running" || job.status === "paused"),
      ),
    [visibleJobs],
  );

  const startV2Generation = useCallback(async (payload: V2GenerationStartPayload) => {
    setLastError(null);
    const job = await api.startV2Generation(payload);
    setDismissedV2JobIds((current) => {
      if (!current.has(job.job_id)) return current;
      const next = new Set(current);
      next.delete(job.job_id);
      return next;
    });
    setV2Jobs((current) => upsertJob(current, job));
    return job;
  }, []);

  const cancelV2Job = useCallback(async (jobId: string) => {
    try {
      setLastError(null);
      const job = await api.cancelV2GenerationJob(jobId);
      setV2Jobs((current) => upsertJob(current, job));
    } catch (err) {
      setLastError(err instanceof Error ? err.message : "Failed to cancel job");
    }
  }, []);

  const dismissV2Job = useCallback((jobId: string) => {
    setDismissedV2JobIds((current) => new Set(current).add(jobId));
  }, []);

  const isV2GenerationActive = useCallback(
    () => visibleV2Jobs.some((job) => job.status === "queued" || job.status === "running"),
    [visibleV2Jobs],
  );

  const value = useMemo(
    () => ({
      jobs: visibleJobs,
      startGeneration,
      startCharacterGeneration,
      cancelJob,
      pauseJob,
      resumeJob,
      dismissJob,
      isGeneratingSeries,
      isGeneratingCharacters,
      lastError,
      clearLastError: () => setLastError(null),
      v2Jobs: visibleV2Jobs,
      startV2Generation,
      cancelV2Job,
      dismissV2Job,
      isV2GenerationActive,
    }),
    [
      visibleJobs,
      startGeneration,
      startCharacterGeneration,
      cancelJob,
      pauseJob,
      resumeJob,
      dismissJob,
      isGeneratingSeries,
      isGeneratingCharacters,
      lastError,
      visibleV2Jobs,
      startV2Generation,
      cancelV2Job,
      dismissV2Job,
      isV2GenerationActive,
    ],
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
