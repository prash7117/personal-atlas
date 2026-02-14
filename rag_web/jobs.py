# Copyright (c) 2026 Prashanth Shankar Narayan
# SPDX-License-Identifier: Apache-2.0

"""Ingestion job management and locking."""

import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rag_web import config


@dataclass
class IngestJob:  # pylint: disable=too-many-instance-attributes
    """In-memory representation of an ingest job."""

    job_id: str
    path: str
    paths: List[str]
    repo_id: str
    entries: List[Dict]
    delete_missing: bool
    status: str = "queued"
    started_ts: Optional[float] = None
    ended_ts: Optional[float] = None
    returncode: Optional[int] = None
    pid: Optional[int] = None
    logs: List[str] = field(default_factory=list)
    stderr: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Return a JSON-serializable job summary."""
        return {
            "job_id": self.job_id,
            "path": self.path,
            "paths": self.paths,
            "repo_id": self.repo_id,
            "entries": self.entries,
            "delete_missing": self.delete_missing,
            "status": self.status,
            "started_ts": self.started_ts,
            "ended_ts": self.ended_ts,
            "returncode": self.returncode,
        }


class JobManager:
    """Manage ingest jobs and enforce single-job execution."""

    def __init__(self) -> None:
        self._jobs: Dict[str, IngestJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = asyncio.Lock()

    async def start_job(
        self, entries: List[Dict], delete_missing: bool, openai_api_key: str
    ) -> Tuple[Optional[IngestJob], Optional[Dict]]:
        """Start a new ingest job if none is running."""
        async with self._lock:
            active = self.get_active_job()
            if active and active.status in ("queued", "starting", "running"):
                return None, {"job_id": active.job_id}

            lock_info = self._read_lock()
            if lock_info:
                pid = lock_info.get("pid")
                if pid and self._pid_running(pid):
                    return None, {"job_id": lock_info.get("job_id"), "pid": pid}
                self._clear_lock()

            repo_label = "multi" if len(entries) > 1 else ""
            first_entry = entries[0] if entries else {}
            repo_id = ""
            paths: List[str] = []
            if isinstance(first_entry, dict):
                repo_id = str(first_entry.get("repo_id") or "")
                paths_value = first_entry.get("paths")
                if isinstance(paths_value, list):
                    paths = [str(path) for path in paths_value if path]

            job_id = self._make_job_id(repo_label or repo_id)
            path = paths[0] if paths else ""
            job = IngestJob(
                job_id=job_id,
                path=path,
                paths=paths,
                repo_id=repo_id,
                entries=entries,
                delete_missing=delete_missing,
            )
            job.status = "starting"
            self._jobs[job_id] = job
            self._active_job_id = job_id

            asyncio.create_task(self._run_job(job, openai_api_key))
            return job, None

    def get_job(self, job_id: str) -> Optional[IngestJob]:
        """Return a job by id."""
        return self._jobs.get(job_id)

    def get_active_job(self) -> Optional[IngestJob]:
        """Return the currently active job, if any."""
        if not self._active_job_id:
            return None
        return self._jobs.get(self._active_job_id)

    def _make_job_id(self, repo_id: str) -> str:
        """Create a timestamped job id."""
        ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        safe_repo = re.sub(r"[^A-Za-z0-9_-]+", "_", repo_id or "repo")
        return f"{ts}-{safe_repo}"

    def _read_lock(self) -> Optional[Dict]:
        """Read the ingest lock file if present."""
        if not config.LOCK_PATH.exists():
            return None
        try:
            return json.loads(config.LOCK_PATH.read_text(encoding="utf-8"))
        except Exception:  # pylint: disable=broad-exception-caught
            return None

    def _write_lock(self, job: IngestJob, pid: int) -> None:
        """Write the ingest lock file."""
        payload = {
            "job_id": job.job_id,
            "pid": pid,
            "started_ts": job.started_ts,
        }
        config.LOCK_PATH.write_text(json.dumps(payload), encoding="utf-8")

    def _clear_lock(self) -> None:
        """Remove the ingest lock file if present."""
        try:
            config.LOCK_PATH.unlink()
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    def _pid_running(self, pid: int) -> bool:
        """Check whether a process id appears to be running."""
        if pid <= 0:
            return False
        return Path(f"/proc/{pid}").exists()

    async def _run_job(self, job: IngestJob, openai_api_key: str) -> None:
        """Execute ingest.py and capture logs."""
        job.started_ts = time.time()
        job.status = "running"
        env = os.environ.copy()
        env["OPENAI_API_KEY"] = openai_api_key

        try:
            entries = job.entries or [{"repo_id": job.repo_id, "paths": job.paths}]
            total_repos = len(entries)
            ran_any = False
            failed = False
            for repo_idx, entry in enumerate(entries, start=1):
                if not isinstance(entry, dict):
                    continue
                repo_id = str(entry.get("repo_id") or "")
                paths_value = entry.get("paths")
                paths: List[str] = []
                if isinstance(paths_value, list):
                    paths = [str(path) for path in paths_value if path]
                if total_repos > 1:
                    job.logs.append(
                        f"== Ingest repo {repo_idx}/{total_repos}: {repo_id}"
                    )
                if not paths:
                    job.logs.append(
                        f"WARN: no paths to ingest for repo {repo_id or 'unknown'}"
                    )
                    continue
                total_paths = len(paths)
                for idx, path in enumerate(paths, start=1):
                    job.logs.append(f"== Ingest root {idx}/{total_paths}: {path}")
                    cmd = [
                        sys.executable,
                        str(config.INGEST_SCRIPT),
                        path,
                        "--repo-id",
                        repo_id,
                    ]
                    if job.delete_missing:
                        cmd.append("--delete-missing")

                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=str(config.BASE_DIR),
                        env=env,
                    )
                    job.pid = proc.pid
                    self._write_lock(job, proc.pid)
                    ran_any = True

                    await asyncio.gather(
                        self._read_stream(proc.stdout, job, is_err=False),
                        self._read_stream(proc.stderr, job, is_err=True),
                    )
                    job.returncode = await proc.wait()
                    if job.returncode != 0:
                        failed = True
                        break
                if failed:
                    break

            if not ran_any:
                job.logs.append("ERROR: no valid ingest paths to run")
                job.returncode = 1
        except Exception as exc:  # pylint: disable=broad-exception-caught
            job.logs.append(f"ERROR: failed to start ingest: {exc}")
            job.stderr.append(str(exc))
            job.returncode = 1
        finally:
            job.ended_ts = time.time()
            if job.returncode == 0:
                job.status = "done"
            else:
                job.status = "error"
            self._clear_lock()
            self._active_job_id = None

    async def _read_stream(self, stream, job: IngestJob, is_err: bool) -> None:
        """Read a subprocess stream into job logs."""
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="ignore").rstrip("\n")
            if is_err:
                job.stderr.append(text)
                job.logs.append(f"ERR: {text}")
            else:
                job.logs.append(text)
