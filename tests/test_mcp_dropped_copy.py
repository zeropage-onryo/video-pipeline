"""The copy Claude Desktop drops must leave before it touches the database.

Desktop starts the stdio server, ends its stdin within a millisecond and
starts another two seconds later, which it keeps (2026-10-10, the desktop's
own log). The first was never killed: it ran the whole table setup with
nobody listening, and because setups take turns (db.run_init) the kept copy
waited behind it -- ~30s to answer `initialize` against the live database
instead of ~17.

Two things are under test, and the second matters more than the first:
the dropped copy leaves without connecting, and NOTHING ELSE does. mcp 2.x
reads the wire from its own duplicate of fd 0, so a check that read or
peeked sys.stdin would swallow the kept copy's first request; a check that
fired on an open pipe would make the desktop show "Server disconnected".
Hence real descriptors here, and real processes at the end.
"""
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pytest

from src import db, mcp_server

ROOT = Path(__file__).resolve().parent.parent
# conftest pins mcp_server.stdin_dropped to False for every test (the
# runner's own fd 0 is not the suite's business). This is the real one,
# taken at import, before any fixture has run.
REAL_CHECK = mcp_server.stdin_dropped
REQUEST = (json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
    "protocolVersion": "2025-06-18", "capabilities": {},
    "clientInfo": {"name": "test", "version": "0"}}}) + "\n")


# ---------- the check itself, on descriptors made here ----------

def test_the_other_end_closed_with_nothing_written_is_hung_up():
    r, w = os.pipe()
    os.close(w)
    try:
        assert mcp_server.hung_up(r)
    finally:
        os.close(r)


def test_a_socket_whose_peer_closed_is_hung_up():
    """What a child of a Node parent gets: Node hands it a socketpair, not
    a pipe (measured against Node 24 -- `stdin.end()` reads as this)."""
    ours, theirs = socket.socketpair()
    theirs.close()
    try:
        assert mcp_server.hung_up(ours.fileno())
    finally:
        ours.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="Linux reports a half-close as POLLRDHUP, "
                    "not POLLHUP, and such a copy is served as before -- the safe side")
def test_a_half_closed_socket_is_hung_up_on_the_mac():
    ours, theirs = socket.socketpair()
    theirs.shutdown(socket.SHUT_WR)
    try:
        assert mcp_server.hung_up(ours.fileno())
    finally:
        ours.close()
        theirs.close()


def test_an_open_pipe_is_served_whatever_is_on_it():
    r, w = os.pipe()
    try:
        assert not mcp_server.hung_up(r)            # nothing written yet
        os.write(w, REQUEST.encode())
        assert not mcp_server.hung_up(r)            # a request waiting
        assert os.read(r, 65536) == REQUEST.encode(), "the check consumed the request"
    finally:
        os.close(r)
        os.close(w)


def test_a_request_written_and_then_closed_is_still_served():
    """A client that sends and hangs up is owed its answer -- and the
    bytes must still be there for the transport to read."""
    r, w = os.pipe()
    os.write(w, REQUEST.encode())
    os.close(w)
    try:
        assert not mcp_server.hung_up(r)
        assert os.read(r, 65536) == REQUEST.encode()
    finally:
        os.close(r)


def test_an_open_socket_is_served():
    ours, theirs = socket.socketpair()
    try:
        assert not mcp_server.hung_up(ours.fileno())
        theirs.sendall(REQUEST.encode())
        assert not mcp_server.hung_up(ours.fileno())
        theirs.close()                              # sent, then gone
        assert not mcp_server.hung_up(ours.fileno())
    finally:
        ours.close()


def test_anything_that_is_not_a_hung_up_pipe_is_served():
    """/dev/null, a file, a descriptor that is closed or never was one:
    the check knows nothing about these, and not knowing means serve."""
    null = os.open(os.devnull, os.O_RDONLY)
    try:
        assert not mcp_server.hung_up(null)
    finally:
        os.close(null)
    with tempfile.TemporaryFile() as empty:
        assert not mcp_server.hung_up(empty.fileno())
    r, w = os.pipe()
    os.close(r)
    os.close(w)
    assert not mcp_server.hung_up(r)
    assert not mcp_server.hung_up(-1)


def test_a_platform_without_poll_serves(monkeypatch):
    import select

    monkeypatch.delattr(select, "poll")
    r, w = os.pipe()
    os.close(w)
    try:
        assert not mcp_server.hung_up(r)
    finally:
        os.close(r)


# ---------- which stdin it is allowed to judge ----------

def test_a_replaced_stdin_is_not_judged(monkeypatch):
    """Only fd 0 is the transport's wire. A test runner's or an embedder's
    stand-in is read in place, so fd 0's state says nothing about it."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert REAL_CHECK() is False
    monkeypatch.setattr(sys, "stdin", None)
    assert REAL_CHECK() is False


def test_a_stdin_on_another_descriptor_is_not_judged(monkeypatch):
    r, w = os.pipe()
    os.close(w)
    with os.fdopen(r) as elsewhere:     # hung up, but it is not fd 0
        assert mcp_server.hung_up(elsewhere.fileno())
        monkeypatch.setattr(sys, "stdin", elsewhere)
        assert REAL_CHECK() is False


# ---------- main(): leave before the database ----------

def test_a_dropped_copy_returns_before_any_init(pg, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(mcp_server, "stdin_dropped", lambda: True)
    monkeypatch.setattr(db, "run_init", lambda *a, **kw: called.append("init"))
    monkeypatch.setattr(mcp_server, "build_server", lambda **kw: called.append("server"))
    assert mcp_server.main(["--db", pg]) == 0
    assert called == []
    assert "nobody to serve" in capsys.readouterr().err


# ---------- the real process, on a real fd 0 ----------

def _tables(dsn):
    with psycopg.connect(dsn) as conn:
        return conn.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = current_schema()").fetchone()[0]


def _launch(dsn):
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           "PYTHONPATH": str(ROOT), "DATABASE_URL": dsn, "RAG_DATABASE_URL": dsn}
    return subprocess.Popen(
        [sys.executable, "-m", "src.mcp_server", "--db", dsn], cwd=str(ROOT), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _first_line(proc, timeout=120):
    """The process's first line of stdout, or a failed test. Never a hung
    one: a check that swallowed the request would leave the server
    waiting for input that is not coming, and this reading forever."""
    import threading

    got = []
    reader = threading.Thread(target=lambda: got.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    if not got:
        proc.kill()
        pytest.fail(f"no answer in {timeout}s -- the request never reached the transport")
    return got[0]


def test_a_process_dropped_at_once_never_touches_the_database(pg_factory):
    """An EMPTY schema: before the check, this left every table in it."""
    dsn = pg_factory()
    proc = _launch(dsn)
    proc.stdin.close()
    out, err = proc.stdout.read(), proc.stderr.read()
    assert proc.wait(timeout=120) == 0, err
    assert out == ""
    assert "nobody to serve" in err
    assert _tables(dsn) == 0


def test_a_process_that_is_kept_answers_its_first_request(pg_factory):
    """The request is written before the process has finished importing,
    as the desktop writes it, and stdin stays open: it must still be
    there when the transport starts reading."""
    dsn = pg_factory()
    proc = _launch(dsn)
    try:
        proc.stdin.write(REQUEST)
        proc.stdin.flush()
        line = _first_line(proc)
    finally:
        proc.stdin.close()
        err = proc.stderr.read()
        code = proc.wait(timeout=120)
    answer = json.loads(line or "null")
    assert answer and answer["id"] == 0 and "result" in answer, (line, err[-400:])
    assert code == 0, err[-400:]
    assert "nobody to serve" not in err
    assert _tables(dsn) > 0


def test_a_process_left_open_and_silent_waits_to_be_asked(pg_factory):
    """Nothing written, nothing closed: a client that is slow to speak,
    or the server run in a terminal (ops/connect-claude.md, step 2 --
    "it should print nothing and sit there"). It must still be running
    when the request finally comes, and answer it."""
    dsn = pg_factory()
    proc = _launch(dsn)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            proc.wait(timeout=4)        # a wrong exit happens within ~1s
        proc.stdin.write(REQUEST)
        proc.stdin.flush()
        line = _first_line(proc)
    finally:
        proc.stdin.close()
        err = proc.stderr.read()
        proc.wait(timeout=120)
    answer = json.loads(line or "null")
    assert answer and answer["id"] == 0 and "result" in answer, (line, err[-400:])


def test_a_process_whose_client_sent_and_hung_up_still_answers(pg_factory):
    """communicate() writes the request and closes stdin before the
    process has looked: hung up, with a request pending. Serve it."""
    dsn = pg_factory()
    proc = _launch(dsn)
    out, err = proc.communicate(REQUEST, timeout=120)
    assert "nobody to serve" not in err
    answer = json.loads(out.splitlines()[0]) if out.strip() else None
    assert answer and answer["id"] == 0 and "result" in answer, (out, err[-400:])
    assert proc.returncode == 0, err[-400:]
