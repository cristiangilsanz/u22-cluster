from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


class DockerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    code: int
    output: str


class Docker:
    def __init__(self, executable: str | None = None) -> None:
        self.executable = executable or shutil.which("docker") or "docker"

    def capture(self, *args: str, stdin: str | None = None) -> Result:
        try:
            completed = subprocess.run(
                [self.executable, *args],
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as error:
            raise DockerError("Docker is not installed or not on the PATH") from error
        return Result(completed.returncode, completed.stdout + completed.stderr)

    def check(self, *args: str, stdin: str | None = None) -> str:
        result = self.capture(*args, stdin=stdin)
        if result.code != 0:
            raise DockerError(result.output.strip() or f"docker {args[0]} failed")
        return result.output

    def attach(self, *args: str, stdin: str | None = None) -> int:
        try:
            return subprocess.run(
                [self.executable, *args], input=stdin, text=True, check=False
            ).returncode
        except FileNotFoundError as error:
            raise DockerError("Docker is not installed or not on the PATH") from error
