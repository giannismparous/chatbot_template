from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies.auth import require_admin_token
from apps.api.dependencies.stack import get_stack
from apps.api.schemas import TraceDetailDTO
from packages.core.admin.roles import AdminContext

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin-traces"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/traces/{trace_id}", response_model=TraceDetailDTO)
def get_trace(
    trace_id: str,
    client_id: Optional[str] = Query(default=None),
    admin: AdminContext = Depends(require_admin_token),
) -> TraceDetailDTO:
    _ = admin
    record = get_stack().trace_store.get(trace_id, client_id=client_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found.")
    return TraceDetailDTO(
        trace_id=record.trace_id,
        client_id=record.client_id,
        session_id=record.session_id,
        created_at=record.created_at.isoformat(),
        privacy_mode=record.privacy_mode,
        trace=record.payload,
    )
