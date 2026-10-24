from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from u22_cluster.cluster import Cluster, ClusterError, Node
from u22_cluster.compose import DEFAULT_UBUNTU
from u22_cluster.docker import DockerError

MAX_NODES = 64


def positive(limit: int):
    def parse(value: str) -> int:
        number = int(value)
        if not 1 <= number <= limit:
            raise argparse.ArgumentTypeError(f"choose a number between 1 and {limit}")
        return number

    return parse


def table(nodes: list[Node]) -> list[str]:
    rows = [("NODE", "STATE", "ADDRESS", "CONTAINER")]
    rows += [(node.name, node.health or node.state, node.address, node.container) for node in nodes]
    widths = [max(len(row[column]) for row in rows) for column in range(4)]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    ]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="u22",
        description="Run a small cluster of Ubuntu containers that trust each other over SSH.",
    )
    root.add_argument(
        "--project",
        default=os.environ.get("U22_PROJECT", "u22"),
        help="name of the cluster, so several can run side by side",
    )
    commands = root.add_subparsers(dest="command", required=True, metavar="command")

    build = commands.add_parser("build", help="build the node image")
    build.add_argument("--ubuntu", default=DEFAULT_UBUNTU, help="Ubuntu release for the nodes")

    start = commands.add_parser("start", help="start the cluster with the given number of nodes")
    start.add_argument("nodes", type=positive(MAX_NODES))
    start.add_argument("--ubuntu", default=DEFAULT_UBUNTU, help="Ubuntu release for the nodes")
    start.add_argument("--work", type=Path, default=Path.cwd(), help="folder shared as /work")
    start.add_argument("--nfs", action="store_true", help="run an NFS server on every node")

    commands.add_parser("status", help="show the nodes and their addresses")

    shell = commands.add_parser("shell", help="open a shell on a node")
    shell.add_argument("node", help="node number or name, such as 2 or node2")

    run = commands.add_parser("run", help="run a command on one node or on all of them")
    run.add_argument("node", help="node number, node name or all")
    run.add_argument("argv", nargs=argparse.REMAINDER, metavar="command")

    mpirun = commands.add_parser("mpirun", help="launch an MPI program across the cluster")
    mpirun.add_argument("-n", "--processes", type=positive(4096), required=True)
    mpirun.add_argument("argv", nargs=argparse.REMAINDER, metavar="command")

    commands.add_parser("stop", help="stop and remove the nodes")
    commands.add_parser("destroy", help="remove the nodes, their shared data and the images")
    return root


def strip_separator(argv: list[str]) -> list[str]:
    return argv[1:] if argv[:1] == ["--"] else argv


def dispatch(cluster: Cluster, args: argparse.Namespace) -> int:
    if args.command == "build":
        cluster.build(args.ubuntu)
        print(f"Built the Ubuntu {args.ubuntu} node image")
        return 0
    if args.command == "start":
        print(f"Starting {args.nodes} node(s) with Ubuntu {args.ubuntu}...")
        nodes = cluster.start(args.nodes, args.work, args.ubuntu, args.nfs)
        print("\n".join(table(nodes)))
        return 0
    if args.command == "status":
        nodes = cluster.nodes()
        print("\n".join(table(nodes)) if nodes else "The cluster is not running")
        return 0
    if args.command == "shell":
        return cluster.shell(args.node)
    if args.command in ("run", "mpirun"):
        command = strip_separator(args.argv)
        if not command:
            raise ClusterError(f"tell {args.command} which command to run")
        if args.command == "run":
            return cluster.run(args.node, command)
        return cluster.mpirun(args.processes, command)
    if args.command == "stop":
        cluster.stop()
        print("Stopped the cluster")
        return 0
    cluster.destroy()
    print("Removed the cluster, its shared data and the node images")
    return 0


def main(argv: Sequence[str] | None = None, cluster: Cluster | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return dispatch(cluster or Cluster(args.project), args)
    except (ClusterError, DockerError, ValueError) as error:
        print(f"u22: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def entry() -> None:
    sys.exit(main())
