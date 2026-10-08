# SPDX-License-Identifier: AGPL-3.0-only
import secrets
from fastapi import HTTPException, Request, Depends
from hashlib import sha256
from sqlalchemy import select
from app.core.database import get_db
from app.models import ReportCredential
from app.core.config import settings

def authorize(request: Request):
    token = settings.admin_token
    if not token:
        raise HTTPException(503, 'Authentication is not configured')
    supplied = request.headers.get('authorization', '')
    if not secrets.compare_digest(supplied.encode('utf-8'), ('Bearer ' + token.get_secret_value()).encode('utf-8')):
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})

def admin(request: Request):
    authorize(request)

def reporter(request: Request, db=Depends(get_db)):
    supplied = request.headers.get('authorization', '')
    if not supplied.startswith('Bearer ') or len(supplied) > 256:
        raise HTTPException(401, 'Reporting credential required')
    digest = sha256(supplied[7:].encode('utf-8')).hexdigest()
    credential = db.scalar(select(ReportCredential).where(ReportCredential.token_digest == digest, ReportCredential.revoked_at.is_(None)))
    if credential is None:
        raise HTTPException(401, 'Invalid or revoked reporting credential')
    return credential
