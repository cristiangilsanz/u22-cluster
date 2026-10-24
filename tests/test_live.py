import os
import shutil
import uuid
from pathlib import Path

import pytest

from u22_cluster.cluster import Cluster

pytestmark = pytest.mark.skipif(
    os.environ.get("U22_LIVE") != "1", reason="set U22_LIVE=1 to start real containers"
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module")
def work(tmp_path_factory):
    folder = tmp_path_factory.mktemp("work")
    shutil.copy(EXAMPLES / "hello.c", folder / "hello.c")
    folder.chmod(0o777)
    return folder


@pytest.fixture(scope="module")
def cluster(work):
    instance = Cluster(f"u22test{uuid.uuid4().hex[:6]}")
    instance.start(3, work, timeout=180)
    yield instance
    instance.docker.check(
        "compose", "--project-name", instance.project, "down", "--volumes", "--remove-orphans"
    )


def lines(cluster, target, *command):
    collected = []
    code = cluster.run(target, list(command), output=collected.append)
    return code, collected


def test_nodes_are_named_and_healthy(cluster):
    nodes = cluster.nodes()
    assert [node.name for node in nodes] == ["node1", "node2", "node3"]
    assert all(node.health == "healthy" for node in nodes)
    assert len({node.address for node in nodes}) == 3


def test_nodes_reach_each_other_by_name_over_ssh(cluster):
    assert lines(cluster, "1", "ssh", "node3", "hostname") == (0, ["node3"])
    assert lines(cluster, "3", "ssh", "node2", "hostname") == (0, ["node2"])


def test_every_node_shares_the_same_hostfile(cluster):
    code, output = lines(cluster, "all", "cat", "/cluster/hostfile")
    assert code == 0
    assert output == [f"node{n} | node{m}" for n in (1, 2, 3) for m in (1, 2, 3)]


def test_the_work_folder_is_shared(cluster, work):
    (work / "note.txt").write_text("shared")
    assert lines(cluster, "2", "cat", "note.txt") == (0, ["shared"])


def test_mpi_programs_run_on_every_node(cluster):
    assert lines(cluster, "1", "mpicc", "hello.c", "-o", "hello")[0] == 0
    code, output = lines(cluster, "1", "mpiexec", "-n", "6", "./hello")
    assert code == 0
    assert len(output) == 6
    assert {line.rsplit(" ", 1)[-1] for line in output} == {"node1", "node2", "node3"}


def test_rpcbind_runs_on_every_node(cluster):
    code, output = lines(cluster, "all", "rpcinfo", "-p")
    assert code == 0
    assert sum("portmapper" in line for line in output) >= 3


def test_failing_commands_report_their_exit_code(cluster):
    assert cluster.run("2", ["bash", "-c", "exit 7"], output=lambda line: None) == 7


def test_stopping_removes_every_node(work):
    temporary = Cluster(f"u22stop{uuid.uuid4().hex[:6]}")
    temporary.start(2, work, timeout=180)
    assert len(temporary.nodes()) == 2
    temporary.stop()
    assert temporary.nodes() == []
    temporary.docker.check("volume", "rm", f"{temporary.project}_cluster")


def test_nfs_shares_mount_across_nodes_and_stop_cleanly(work):
    shared = Cluster(f"u22nfs{uuid.uuid4().hex[:6]}")
    shared.start(2, work, nfs=True, timeout=180)
    try:
        assert lines(shared, "1", "showmount", "-e", "localhost")[1][-1].startswith("/export")
        mount = "mkdir -p /mnt/node1 && mount -t nfs node1:/export /mnt/node1"
        assert shared.run("2", ["bash", "-c", mount], output=lambda line: None) == 0
        assert shared.run("2", ["bash", "-c", "echo hi > /mnt/node1/note"], output=print) == 0
        assert lines(shared, "1", "cat", "/export/note") == (0, ["hi"])
    finally:
        shared.stop()
    assert shared.nodes() == []
    shared.docker.check(
        "compose", "--project-name", shared.project, "down", "--volumes", "--remove-orphans"
    )
