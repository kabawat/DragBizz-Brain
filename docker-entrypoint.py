"""Fix the bind-mounted audit directory, then run as the dragbizz user.

Host `./data` is often created root:root 755 by Docker. The app user cannot
append `tool_audit.jsonl` until that directory is writable.
"""

from __future__ import annotations

import os
import pwd
import sys

DATA_DIR = "/app/data"


def _prepare_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    # Sticky and world-writable so both the container user and the host
    # user can create the audit file on a shared bind mount.
    os.chmod(DATA_DIR, 0o1777)
    audit_file = os.path.join(DATA_DIR, "tool_audit.jsonl")
    if os.path.isfile(audit_file):
        os.chmod(audit_file, 0o666)


def _drop_privileges() -> None:
    user = pwd.getpwnam("dragbizz")
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
    os.environ["HOME"] = user.pw_dir


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("docker-entrypoint: missing command")
    if os.geteuid() == 0:
        _prepare_data_dir()
        _drop_privileges()
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
