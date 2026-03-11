import re
from pathlib import Path


class EnvFileService:
    def __init__(self) -> None:
        self._env_path = Path(".env")
        self._example_path = Path(".env.example")

    def get_env_path(self) -> Path:
        return self._env_path

    def ensure_env_file(self) -> Path:
        if self._env_path.exists():
            if self._env_path.is_dir():
                raise ValueError(".env 路径当前是目录，无法写入配置")
            return self._env_path

        if self._example_path.exists() and self._example_path.is_file():
            self._env_path.write_text(self._example_path.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            self._env_path.write_text("", encoding="utf-8")
        return self._env_path

    def update_values(self, values: dict[str, str | None]) -> Path:
        env_path = self.ensure_env_file()
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()
        normalized_values = {
            key: str(value or "").strip()
            for key, value in values.items()
            if key
        }
        patterns = {
            key: re.compile(rf"^\s*{re.escape(key)}\s*=")
            for key in normalized_values
        }
        consumed_keys: set[str] = set()
        next_lines: list[str] = []

        for line in existing_lines:
            replaced = False
            for key, pattern in patterns.items():
                if not pattern.match(line):
                    continue
                consumed_keys.add(key)
                cleaned = normalized_values[key]
                if cleaned:
                    next_lines.append(f"{key}={cleaned}")
                replaced = True
                break
            if not replaced:
                next_lines.append(line)

        for key, cleaned in normalized_values.items():
            if key in consumed_keys or not cleaned:
                continue
            next_lines.append(f"{key}={cleaned}")

        content = "\n".join(next_lines).rstrip()
        if content:
            content += "\n"
        env_path.write_text(content, encoding="utf-8")

        return env_path


env_file_service = EnvFileService()
