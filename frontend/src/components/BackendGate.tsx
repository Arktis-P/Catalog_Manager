import { useEffect, useState, type ReactNode } from "react";
import { waitForBackend } from "../api/client";

interface BackendGateProps {
  children: ReactNode;
}

export function BackendGate({ children }: BackendGateProps) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setError(null);

    void waitForBackend()
      .then(() => {
        if (!cancelled) {
          setReady(true);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "백엔드에 연결하지 못했습니다.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  if (error) {
    return (
      <div className="page-container">
        <section className="panel" style={{ marginTop: "2rem" }}>
          <h1 className="page-title">백엔드 연결 실패</h1>
          <p className="page-description" style={{ whiteSpace: "pre-wrap" }}>
            {error}
          </p>
          <div className="card-actions" style={{ marginTop: "1rem" }}>
            <button className="btn btn-primary" type="button" onClick={() => setRetryKey((key) => key + 1)}>
              다시 연결
            </button>
          </div>
        </section>
      </div>
    );
  }

  if (!ready) {
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
