from __future__ import annotations

from apps.worker.jobs.db_seed import run_db_seed
from apps.worker.jobs.vector_index_build import run_vector_index_build

def run_index_build() -> None:
    """
    Entry point for chunk/embed/index jobs.
    Seeds structured chunk data into the default DB connector.
    """
    run_db_seed()
    run_vector_index_build()


if __name__ == "__main__":
    run_index_build()
