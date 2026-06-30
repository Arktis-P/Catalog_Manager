import { useEffect, useState, type ReactNode } from "react";
import { waitForBackend } from "../api/client";

interface BackendGateProps {
  children: ReactNode;
}

type GateState = "connecting" | "ready" | "error";

const HEALTH_CHECK_INTERVAL_MS = 10_000;

export function BackendGate({ children }: BackendGateProps) {
  const [gateState, setGateState] = useState<GateState>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  // 초기 연결 (재시도 포함)
  useEffect(() => {
    let cancelled = false;
    setGateState("connecting");
    setError(null);

    void waitForBackend()
      .then(() => {
        if (!cancelled) setGateState("ready");
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setGateState("error");
          setError(err instanceof Error ? err.message : "백엔드에 연결하지 못했습니다.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  // 연결 완료 후 주기적 헬스체크 — 백엔드 다운 시 즉시 재연결 화면으로 전환
  useEffect(() => {
    if (gateState !== "ready") return;

    const check = async () => {
      try {
        const res = await fetch("/api/health", {
          signal: AbortSignal.timeout(3000),
        });
        if (!res.ok) throw new Error("not ok");
      } catch {
        setRetryKey((k) => k + 1);
      }
    };

    const timer = window.setInterval(() => void check(), HEALTH_CHECK_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [gateState]);

  if (gateState === "error") {
    return (
      <div className="page-container">
        <section className="panel" style={{ marginTop: "2rem" }}>
          <h1 className="page-title">백엔드 연결 실패</h1>
          <p className="page-description" style={{ whiteSpace: "pre-wrap" }}>
            {error}
          </p>
          <div className="backend-gate-hint">
            <strong>해결 방법</strong>
            <ol>
              <li>이 창을 닫고 <code>scripts\launch_desktop.bat</code>을 다시 실행하세요.</li>
              <li>백엔드가 이미 실행 중이라면 아래 "다시 연결" 버튼을 누르세요.</li>
            </ol>
          </div>
          <div className="card-actions" style={{ marginTop: "1rem" }}>
            <button
              className="btn btn-primary"
              type="button"
              onClick={() => setRetryKey((key) => key + 1)}
            >
              다시 연결
            </button>
          </div>
        </section>
      </div>
    );
  }

  if (gateState === "connecting") {
    return (
      <div className="page-container">
        <section className="panel" style={{ marginTop: "2rem" }}>
          <h1 className="page-title">Catalogue Manager</h1>
          <p className="page-description">백엔드 서버에 연결하는 중...</p>
        </section>
      </div>
    );
  }

  return <>{children}</>;
}
