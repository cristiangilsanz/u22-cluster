import pytest
from fakes import FakeDocker, container

from u22_cluster.cli import main, table
from u22_cluster.cluster import Cluster
from u22_cluster.docker import DockerError


def run(argv, *containers, **options):
    docker = FakeDocker(list(containers), **options)
    cluster = Cluster("lab", docker, clock=iter(range(1000)).__next__, sleep=lambda s: None)
    return main(argv, cluster), docker


def test_status_prints_a_table(capsys):
    code, _ = run(["status"], container("lab", "node1", address="172.20.0.2"))
    lines = capsys.readouterr().out.splitlines()
    assert code == 0
    assert lines[0].split() == ["NODE", "STATE", "ADDRESS", "CONTAINER"]
    assert lines[1].split() == ["node1", "healthy", "172.20.0.2", "lab-node1"]


def test_status_explains_when_nothing_runs(capsys):
    run(["status"])
    assert "not running" in capsys.readouterr().out


def test_start_prints_the_ready_nodes(capsys, tmp_path):
    code, _ = run(["start", "1", "--work", str(tmp_path)], container("lab", "node1"))
    out = capsys.readouterr().out
    assert code == 0
    assert "Starting 1 node(s) with Ubuntu 22.04" in out
    assert "node1" in out


def test_run_accepts_a_separator(capsys):
    code, docker = run(["run", "all", "--", "ls", "-la"], container("lab", "node1"))
    assert code == 0
    assert docker.calls[-1][-1] == "ls -la"


def test_run_needs_a_command(capsys):
    code, _ = run(["run", "all"], container("lab", "node1"))
    assert code == 1
    assert "which command" in capsys.readouterr().err


def test_errors_are_printed_without_a_traceback(capsys):
    code, _ = run(["shell", "3"], container("lab", "node1"))
    assert code == 1
    assert capsys.readouterr().err.startswith("u22: there is no 3")


def test_missing_docker_is_reported(capsys):
    class Missing(FakeDocker):
        def capture(self, *args, stdin=None):
            raise DockerError("Docker is not installed or not on the PATH")

    docker = Missing()
    code = main(["status"], Cluster("lab", docker))
    assert code == 1
    assert "Docker is not installed" in capsys.readouterr().err


@pytest.mark.parametrize("nodes", ["0", "65", "two"])
def test_node_counts_are_validated(nodes, capsys):
    with pytest.raises(SystemExit):
        main(["start", nodes])


def test_the_table_aligns_columns():
    from u22_cluster.cluster import Node

    rows = table([Node("node1", "lab-node1", "running", "healthy", "172.20.0.2")])
    assert rows[0].index("STATE") == rows[1].index("healthy")
