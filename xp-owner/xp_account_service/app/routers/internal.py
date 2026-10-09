"""Internal credential routes. Every route requires the service token."""

from fastapi import Depends, FastAPI, HTTPException, status

from xp_account_service.app.dependencies import (
    get_credential_service,
    require_internal_token,
)
from xp_account_service.app.schemas.credential import (
    VerifyCredentialRequest,
    VerifyCredentialResponse,
)
from xp_account_service.app.services.credential_service import CredentialService
from xp_account_service.common.errors import InvalidCredentialError

def register(app: FastAPI) -> None:
    app.add_api_route(
        "/internal/credentials/verify",
        verify_credential,
        methods=["POST"],
        response_model=VerifyCredentialResponse,
        dependencies=[Depends(require_internal_token)],
    )


def verify_credential(
    body: VerifyCredentialRequest,
    credential_service: CredentialService = Depends(get_credential_service),
) -> VerifyCredentialResponse:
    try:
        verified = credential_service.verify(body.secret)
    except InvalidCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credential",
        ) from exc
    return VerifyCredentialResponse(
        credential_id=verified.credential_id,
        kind=verified.kind,
    )
