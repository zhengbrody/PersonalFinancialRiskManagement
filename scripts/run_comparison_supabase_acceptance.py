"""Run isolated Auth/PostgREST acceptance; never touch a hosted Supabase project.

Prerequisites: running local Docker, Supabase CLI, backend test dependencies.
Creates only the dedicated local CLI project, restricts its published ports to
loopback, runs the HTTP acceptance suite and stops its containers on exit.
The CLI keeps the local database volume for repeat runs. No production dump,
credentials or application configuration are read. No secret output is printed.
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PROJECT = "mindmarket-staging-20260906"
WORKDIR = Path("/tmp") / PROJECT
ROOT = Path(__file__).resolve().parents[1]


def command(args, timeout=180):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    if result.returncode:
        # CLI start/status/inspect output can include local development secrets.
        raise RuntimeError(f"Local {args[0]} operation failed (exit {result.returncode})")
    return result.stdout


def bind_loopback():
    host = command(["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
    host = host.strip()
    if not host.startswith("unix://"):
        raise RuntimeError("Only a local Docker Unix socket is supported")

    class DockerConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(30)
            self.sock.connect(host[7:])

    def api(method, path, payload=None):
        connection = DockerConnection("localhost", timeout=30)
        try:
            connection.request(
                method,
                "/v1.45" + path,
                json.dumps(payload) if payload is not None else None,
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            data = response.read()
            if response.status >= 300:
                raise RuntimeError(f"Local Docker operation failed ({response.status})")
            return json.loads(data) if data else None
        finally:
            connection.close()

    # The CLI currently publishes on all interfaces, even with a bridge default
    # bind address. Recreate only these two owned containers with the same
    # configuration, mounts and network aliases; never remove database volumes.
    for kind in ("kong", "db"):
        name = f"supabase_{kind}_{PROJECT}"
        original = api("GET", f"/containers/{name}/json")
        if original["Config"]["Labels"].get("com.supabase.cli.project") != PROJECT:
            raise RuntimeError("Container ownership guard failed")
        host_config = original["HostConfig"]
        ports = host_config["PortBindings"]
        if all(row["HostIp"] == "127.0.0.1" for rows in ports.values() for row in rows):
            continue
        for rows in ports.values():
            for row in rows:
                row["HostIp"] = "127.0.0.1"
        networks = {
            name: {"Aliases": values["Aliases"]}
            for name, values in original["NetworkSettings"]["Networks"].items()
        }
        payload = {
            **original["Config"],
            "HostConfig": host_config,
            "NetworkingConfig": {"EndpointsConfig": networks},
        }
        api("POST", f"/containers/{name}/stop?t=15")
        api("DELETE", f"/containers/{name}?v=false")
        api("POST", f"/containers/create?name={name}", payload)
        api("POST", f"/containers/{name}/start")


def main():
    if WORKDIR.is_symlink():
        raise RuntimeError("Refusing a symlinked staging workdir")
    WORKDIR.mkdir(mode=0o700, exist_ok=True)
    if (WORKDIR / "supabase/.temp/project-ref").exists():
        raise RuntimeError("Refusing a linked Supabase project")
    config = WORKDIR / "supabase/config.toml"
    if not config.exists():
        command(["supabase", "init", "--workdir", str(WORKDIR), "--yes"])
    if f'project_id = "{PROJECT}"' not in config.read_text():
        raise RuntimeError("Local project identity mismatch")
    docker_host = command(
        ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"]
    )
    if not docker_host.strip().startswith("unix://"):
        raise RuntimeError("Remote Docker is not supported")
    if os.environ.get("DOCKER_HOST", docker_host.strip()) != docker_host.strip():
        raise RuntimeError("DOCKER_HOST must match the inspected local Docker endpoint")
    try:
        print("Starting dedicated local Supabase; no hosted project connection.", flush=True)
        command(
            [
                "supabase",
                "start",
                "--workdir",
                str(WORKDIR),
                "-x",
                "studio,storage-api,imgproxy,realtime,edge-runtime,logflare,vector,"
                "postgres-meta,mailpit,supavisor",
            ],
            timeout=600,
        )
        bind_loopback()
        for attempt in range(60):
            try:
                command(
                    ["supabase", "status", "--workdir", str(WORKDIR), "--output", "json"],
                    timeout=15,
                )
                break
            except RuntimeError:
                if attempt == 59:
                    raise
                time.sleep(1)
        env = {**os.environ, "MINDMARKET_TEST_SUPABASE_WORKDIR": str(WORKDIR)}
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "backend/tests/test_comparison_save_supabase.py",
                "-q",
                "-o",
                "addopts=",
                "--tb=short",
            ],
            cwd=ROOT,
            env=env,
        ).returncode
    finally:
        print("Stopping only the dedicated local stack; its volume is retained.", flush=True)
        command(["supabase", "stop", "--workdir", str(WORKDIR)])


if __name__ == "__main__":
    sys.exit(main())
