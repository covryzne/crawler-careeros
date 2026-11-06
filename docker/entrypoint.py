"""Start a private virtual display when needed, then exec the requested command.

Exec leaves the worker directly behind Docker init so SIGTERM reaches its cleanup
handler. Xvfb remains a child in the same container and exposes no TCP listener.
"""

import os
import select
import subprocess
import sys


def start_display():
    read_fd, write_fd = os.pipe()
    process = None
    try:
        process = subprocess.Popen(
            [
                "Xvfb",
                "-displayfd",
                str(write_fd),
                "-screen",
                "0",
                "1440x1000x24",
                "-nolisten",
                "tcp",
            ],
            pass_fds=(write_fd,),
        )
        os.close(write_fd)
        write_fd = None
        # Xvfb writes a display number only after it has acquired a display and is ready.
        if not select.select([read_fd], [], [], 15)[0]:
            raise RuntimeError("Virtual display startup timed out")
        number = os.read(read_fd, 32).decode().strip()
        if not number.isdigit() or process.poll() is not None:
            raise RuntimeError("Virtual display failed to start")
        os.environ["DISPLAY"] = f":{number}"
    except BaseException:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        raise
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def main():
    mode = os.environ.get("CRAWLER_BROWSER_MODE", "headless")
    if mode not in {"headed", "headless", "auto"}:
        raise SystemExit("Invalid CRAWLER_BROWSER_MODE; use headed/headless/auto")
    if len(sys.argv) < 2:
        raise SystemExit("A worker command is required")
    if mode in {"headed", "auto"}:
        start_display()
    print(
        f"Crawler container ready: browser_mode={mode} display_ready={bool(os.environ.get('DISPLAY'))}",
        flush=True,
    )
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == "__main__":
    main()
