from __future__ import annotations

import json
import re
import shlex
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib.resources import as_file, files
from pathlib import Path

from u22_cluster.compose import DEFAULT_UBUNTU, Layout, image_name, render
from u22_cluster.docker import Docker

PROJECT_LABEL = "com.docker.compose.project"
NODE_PATTERN = re.compile(r"^(?:node)?(\d+)$")
UNMOUNT_SHARES = "umount -a -l -t nfs,nfs4 2>/dev/null || true"
STOP_SHARING = "exportfs -ua 2>/dev/null; rpc.nfsd 0 2>/dev/null || true"


@dataclass(frozen=True)
class Node:
    name: str
    container: str
    state: str
    health: str
    address: str

    @property
    def index(self) -> int:
        match = NODE_PATTERN.match(self.name)
        return int(match.group(1)) if match else 0

    @property
    def ready(self) -> bool:
        return self.state == "running" and self.health in ("healthy", "")


class ClusterError(RuntimeError):
    pass


def tty_flags() -> list[str]:
    return ["-it"] if sys.stdin.isatty() and sys.stdout.isatty() else ["-i"]


class Cluster:
    def __init__(
        self,
        project: str = "u22",
        docker: Docker | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.project = project
        self.docker = docker or Docker()
        self.clock = clock
        self.sleep = sleep

    def image_exists(self, ubuntu: str = DEFAULT_UBUNTU) -> bool:
        return self.docker.capture("image", "inspect", image_name(ubuntu)).code == 0

    def build(self, ubuntu: str = DEFAULT_UBUNTU) -> None:
        with as_file(files("u22_cluster") / "image") as context:
            code = self.docker.attach(
                "build",
                "--tag",
                image_name(ubuntu),
                "--build-arg",
                f"UBUNTU_VERSION={ubuntu}",
                str(context),
            )
        if code != 0:
            raise ClusterError("the image could not be built")

    def start(
        self,
        size: int,
        work: Path,
        ubuntu: str = DEFAULT_UBUNTU,
        nfs: bool = False,
        timeout: float = 120.0,
    ) -> list[Node]:
        layout = Layout(self.project, size, work.resolve(), ubuntu, nfs)
        definition = render(layout)
        if not self.image_exists(ubuntu):
            self.build(ubuntu)
        self.docker.check(
            "compose", "-f", "-", "up", "--detach", "--remove-orphans", stdin=definition
        )
        return self.wait_until_ready(size, timeout)

    def nodes(self) -> list[Node]:
        names = self.docker.check(
            "ps",
            "--all",
            "--filter",
            f"label={PROJECT_LABEL}={self.project}",
            "--format",
            "{{.Names}}",
        ).split()
        if not names:
            return []
        details = json.loads(self.docker.check("inspect", *names))
        return sorted((self._node(detail) for detail in details), key=lambda node: node.index)

    def _node(self, detail: dict) -> Node:
        state = detail.get("State", {})
        networks = detail.get("NetworkSettings", {}).get("Networks", {}) or {}
        addresses = [network.get("IPAddress", "") for network in networks.values()]
        return Node(
            name=detail.get("Config", {}).get("Hostname", ""),
            container=detail.get("Name", "").lstrip("/"),
            state=state.get("Status", "unknown"),
            health=(state.get("Health") or {}).get("Status", ""),
            address=next((address for address in addresses if address), "-"),
        )

    def wait_until_ready(self, size: int, timeout: float) -> list[Node]:
        deadline = self.clock() + timeout
        while True:
            nodes = self.nodes()
            if len(nodes) == size and all(node.ready for node in nodes):
                return nodes
            failed = [node.name for node in nodes if node.state in ("exited", "dead")]
            if failed:
                raise ClusterError(f"these nodes stopped while starting: {', '.join(failed)}")
            if self.clock() >= deadline:
                raise ClusterError("the nodes did not become ready in time")
            self.sleep(0.5)

    def resolve(self, target: str) -> list[Node]:
        nodes = self.nodes()
        if not nodes:
            raise ClusterError("the cluster is not running, start it with: u22 start <nodes>")
        if target == "all":
            return nodes
        match = NODE_PATTERN.match(target)
        chosen = [node for node in nodes if match and node.index == int(match.group(1))]
        if not chosen:
            raise ClusterError(
                f"there is no {target}, choose one of: {', '.join(n.name for n in nodes)}"
            )
        return chosen

    def shell(self, target: str) -> int:
        [node] = self.resolve(target)
        return self.docker.attach(
            "exec", *tty_flags(), "--workdir", "/work", node.container, "bash", "--login"
        )

    def run(self, target: str, command: list[str], output: Callable[[str], None] = print) -> int:
        nodes = self.resolve(target)
        script = shlex.join(command)

        def execute(node: Node):
            return self.docker.capture(
                "exec", "--workdir", "/work", node.container, "bash", "-lc", script
            )

        with ThreadPoolExecutor(max_workers=len(nodes)) as pool:
            results = list(pool.map(execute, nodes))
        width = max(len(node.name) for node in nodes)
        for node, result in zip(nodes, results, strict=True):
            for line in result.output.rstrip("\n").splitlines():
                output(f"{node.name:<{width}} | {line}" if len(nodes) > 1 else line)
        return max(result.code for result in results)

    def mpirun(self, processes: int, command: list[str]) -> int:
        first = self.resolve("1")[0]
        return self.docker.attach(
            "exec",
            *tty_flags(),
            "--workdir",
            "/work",
            first.container,
            "mpiexec",
            "-n",
            str(processes),
            *command,
        )

    def everywhere(self, nodes: list[Node], script: str) -> None:
        with ThreadPoolExecutor(max_workers=max(1, len(nodes))) as pool:
            for node in nodes:
                pool.submit(self.docker.capture, "exec", node.container, "bash", "-c", script)

    def release_shares(self) -> None:
        running = [node for node in self.nodes() if node.state == "running"]
        self.everywhere(running, UNMOUNT_SHARES)
        self.everywhere(running, STOP_SHARING)

    def stop(self) -> None:
        self.release_shares()
        self.docker.check("compose", "--project-name", self.project, "down", "--remove-orphans")

    def destroy(self) -> None:
        self.release_shares()
        self.docker.check(
            "compose", "--project-name", self.project, "down", "--volumes", "--remove-orphans"
        )
        images = self.docker.check(
            "image", "ls", "u22-cluster", "--format", "{{.Repository}}:{{.Tag}}"
        ).split()
        if images:
            self.docker.check("image", "rm", *images)
