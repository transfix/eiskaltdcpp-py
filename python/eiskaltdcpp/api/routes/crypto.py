"""
Crypto / TLS API routes.

GET  /api/crypto/status              — TLS and certificate status
POST /api/crypto/certificate/generate — Generate a new certificate
POST /api/crypto/certificate/reload   — Reload certificates from disk
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from eiskaltdcpp.api.auth import UserRecord
from eiskaltdcpp.api.dependencies import get_dc_client, require_admin, require_readonly
from eiskaltdcpp.api.models import CryptoStatus, SuccessResponse

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


def _require_client(client):
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DC client not initialized",
        )
    return client


@router.get(
    "/status",
    response_model=CryptoStatus,
    summary="Get TLS / certificate status",
)
async def get_crypto_status(
    _user: UserRecord = Depends(require_readonly),
    client=Depends(get_dc_client),
) -> CryptoStatus:
    client = _require_client(client)
    cm = client.crypto
    return CryptoStatus(tls_ok=cm.TLSOk())


@router.post(
    "/certificate/generate",
    response_model=SuccessResponse,
    summary="Generate new TLS certificate",
)
async def generate_certificate(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    client.crypto.generateCertificate()
    return SuccessResponse(message="Certificate generated")


@router.post(
    "/certificate/reload",
    response_model=SuccessResponse,
    summary="Reload TLS certificates from disk",
)
async def reload_certificates(
    _admin: UserRecord = Depends(require_admin),
    client=Depends(get_dc_client),
) -> SuccessResponse:
    client = _require_client(client)
    ok = client.crypto.loadCertificates()
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load certificates",
        )
    return SuccessResponse(message="Certificates reloaded")
