import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: "2rem", color: "#f88", fontFamily: "monospace", whiteSpace: "pre-wrap" }}>
          <strong>앱 렌더링 오류</strong>
          {"\n\n"}
          {String(this.state.error)}
          {"\n\n"}
          {this.state.error.stack}
        </div>
      );
    }
    return this.props.children;
  }
}
