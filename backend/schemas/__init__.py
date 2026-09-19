"""Pydantic schemas for the AI Time Tracking Backend API.

All API responses use typed Pydantic models so that:
  - OpenAPI spec is auto-generated with full schema detail
  - Frontend can codegen TypeScript types from /openapi.json
  - Validation is enforced at the boundary
"""
