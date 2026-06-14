from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CATALOGUE_")

    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[2])
    database_url: str = ""
    input_dir: Path | None = None
    output_dir: Path | None = None
    serve_gui: bool = False
    frontend_dist_dir: Path | None = None

    def model_post_init(self, __context) -> None:
        if not self.database_url:
            self.database_url = f"sqlite:///{self.project_root / 'data' / 'catalogue.db'}"
        if self.input_dir is None:
            self.input_dir = self.project_root / "input"
        if self.output_dir is None:
            self.output_dir = self.project_root / "output"
        if self.frontend_dist_dir is None:
            self.frontend_dist_dir = self.project_root / "frontend" / "dist"


settings = Settings()
