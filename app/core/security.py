# SPDX-License-Identifier: AGPL-3.0-only
import secrets
from fastapi import HTTPException, Request
from app.core.config import settings

def authorize(request: Request, reporting=False):
    token = settings.report_token if reporting else settings.admin_token
    if not token:
        raise HTTPException(503, 'Authentication is not configured')
    supplied = request.headers.get('authorization', '')
    if not secrets.compare_digest(supplied, 'Bearer ' + token.get_secret_value()):
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})

def admin(request: Request):
    authorize(request)

def reporter(request: Request):
    authorize(request, True)
