from pydantic import BaseModel


class PipelineStatusResponse(BaseModel):
    status: str
    phase: str | None
    collect_total: int
    collect_done: int
    collect_failed: int
    extract_total: int
    extract_done: int
    extract_failed: int
    generate_total: int
    generate_done: int
    generate_failed: int
    auto_generate: bool
    current_series_tag: str | None
    current_job_message: str | None
    started_at: str | None
    finished_at: str | None
    errors: list[str]

    @classmethod
    def from_state(cls, state) -> "PipelineStatusResponse":
        return cls(
            status=state.status,
            phase=state.phase,
            collect_total=state.collect_total,
            collect_done=state.collect_done,
            collect_failed=state.collect_failed,
            extract_total=state.extract_total,
            extract_done=state.extract_done,
            extract_failed=state.extract_failed,
            generate_total=state.generate_total,
            generate_done=state.generate_done,
            generate_failed=state.generate_failed,
            auto_generate=state.auto_generate,
            current_series_tag=state.current_series_tag,
            current_job_message=state.current_job_message,
            started_at=state.started_at,
            finished_at=state.finished_at,
            errors=state.errors,
        )
