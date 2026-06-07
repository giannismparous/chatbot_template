from __future__ import annotations

from apps.worker.jobs.google_drive_sync import run_google_drive_sync

def run_sync() -> None:
    """
    Entry point for source synchronization jobs.
    Orchestrates configured source sync jobs.
    """
    run_google_drive_sync(client_id="default")


if __name__ == "__main__":
    run_sync()
