from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILES = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "input" / "danbooru.env",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CATALOGUE_",
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project_root: Path = Field(default=PROJECT_ROOT)
    database_url: str = ""
    input_dir: Path | None = None
    output_dir: Path | None = None
    serve_gui: bool = False
    frontend_dist_dir: Path | None = None

    danbooru_username: str = ""
    danbooru_api_key: str = ""
    danbooru_base_url: str = "https://danbooru.donmai.us"
    danbooru_request_delay: float = 0.5
    danbooru_character_tag_pages: int = 20
    danbooru_character_post_pages: int = 10
    danbooru_character_post_limit: int = 200

    def model_post_init(self, __context) -> None:
        if not self.database_url:
            self.database_url = f"sqlite:///{self.project_root / 'data' / 'catalogue.db'}"
        if self.input_dir is None:
            self.input_dir = self.project_root / "input"
        if self.output_dir is None:
            self.output_dir = self.project_root / "output"
        if self.frontend_dist_dir is None:
            self.frontend_dist_dir = self.project_root / "frontend" / "dist"

        self._load_danbooru_key_file()

    def _load_danbooru_key_file(self) -> None:
        self._load_simple_env_file(self.input_dir / "danbooru.env")
        self._load_simple_env_file(PROJECT_ROOT / ".env")

        if self.danbooru_api_key:
            return

        key_file = self.input_dir / "danbooru_api_key.txt"
        if not key_file.exists():
            return

        lines = [
            line.strip()
            for line in key_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not lines:
            return

        if len(lines) >= 2:
            if not self.danbooru_username:
                self.danbooru_username = lines[0]
            self.danbooru_api_key = lines[1]
        elif len(lines) == 1:
            self.danbooru_api_key = lines[0]

    def _load_simple_env_file(self, path: Path) -> None:
        if not path.exists():
            return

        for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip().strip('"').strip("'")
            if not value or value.startswith("your_"):
                continue

            if key in {"username", "danbooru_username", "catalogue_danbooru_username"}:
                self.danbooru_username = value.strip()
            elif key in {"api_key", "danbooru_api_key", "catalogue_danbooru_api_key"}:
                self.danbooru_api_key = value.strip()

    @property
    def danbooru_configured(self) -> bool:
        return bool(self.danbooru_username and self.danbooru_api_key)


settings = Settings()
