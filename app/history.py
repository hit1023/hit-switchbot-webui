import datetime
import sqlite3
from pathlib import Path

DB_PATH = Path("/data/history.db")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS command_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            username TEXT NOT NULL,
            device_id TEXT NOT NULL,
            device_name TEXT NOT NULL,
            command TEXT NOT NULL,
            parameter TEXT NOT NULL,
            success INTEGER NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return con


def record(
    username: str,
    device_id: str,
    device_name: str,
    command: str,
    parameter: str,
    success: bool,
    detail: str = "",
) -> None:
    con = _connect()
    with con:
        con.execute(
            "INSERT INTO command_log (ts, username, device_id, device_name, command, parameter, success, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                username,
                device_id,
                device_name,
                command,
                parameter,
                1 if success else 0,
                detail,
            ),
        )
    con.close()


def list_recent(limit: int = 50) -> list[dict]:
    con = _connect()
    rows = con.execute(
        "SELECT ts, username, device_id, device_name, command, parameter, success, detail "
        "FROM command_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    con.close()
    columns = ["ts", "username", "device_id", "device_name", "command", "parameter", "success", "detail"]
    return [dict(zip(columns, row)) for row in rows]
