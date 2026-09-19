"""Common response wrappers and shared schema utilities."""
from __future__ import annotations

from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response envelope."""
    status: str = "success"
    data: T


class ApiListResponse(BaseModel, Generic[T]):
    """Standard API list response with count."""
    status: str = "success"
    count: int
    items: List[T]


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""
    status: str = "success"
    count: int
    total: int
    page: int
    page_size: int
    items: List[T]


class ErrorResponse(BaseModel):
    """Standard error response."""
    status: str = "error"
    detail: str
    code: Optional[str] = None


class HealthCheck(BaseModel):
    """Root health check response."""
    status: str
    version: str
    protocol_version: int = 1
    engine_connected: bool = False
    db_ready: bool = False
    active_cameras: int = 0
    total_configured_cameras: int = 0
