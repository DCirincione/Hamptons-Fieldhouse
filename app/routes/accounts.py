from fastapi import APIRouter, Depends, HTTPException, Request, Response
from httpx import HTTPError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from supabase import Client
from supabase_auth.errors import AuthApiError, AuthError

from app.auth import (ACCESS_COOKIE, REFRESH_COOKIE, clear_session_cookies, current_user,
                      get_auth_client, public_account, require_browser_request, set_session_cookies)
from app.config import Settings, get_settings

router = APIRouter(prefix='/auth', tags=['accounts'], dependencies=[Depends(require_browser_request)])


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Signup(Credentials):
    password: str = Field(min_length=10, max_length=128)
    name: str = Field(min_length=1, max_length=100)


def auth_error(exc):
    if isinstance(exc, AuthApiError) and exc.status == 429:
        return HTTPException(429, 'Too many attempts. Please wait a few minutes and try again.')
    return HTTPException(503, 'The account service is temporarily unavailable. Please try again.')


@router.post('/signup')
def signup(data: Signup, request: Request, response: Response,
           db: Client = Depends(get_auth_client), settings: Settings = Depends(get_settings)):
    if not data.name.strip():
        raise HTTPException(422, 'Please enter your name.')
    try:
        result = db.auth.sign_up({'email': str(data.email), 'password': data.password,
            'options': {'data': {'name': data.name.strip()}, 'email_redirect_to': settings.site_url.rstrip('/') + '/account'}})
    except (AuthError, HTTPError) as exc:
        if isinstance(exc, AuthApiError) and exc.status < 500 and exc.status != 429:
            raise HTTPException(400, 'Unable to create this account. Use a stronger password, or sign in if you already have an account.') from None
        raise auth_error(exc) from None
    response.headers['Cache-Control'] = 'no-store'
    if result.session:
        set_session_cookies(response, request, result.session)
        return {'signed_in': True}
    return {'signed_in': False, 'message': 'Check your email to confirm your account, then return here to sign in. If you already have an account, sign in instead.'}


@router.post('/login')
def login(data: Credentials, request: Request, response: Response, db: Client = Depends(get_auth_client)):
    try:
        result = db.auth.sign_in_with_password({'email': str(data.email), 'password': data.password})
    except (AuthError, HTTPError) as exc:
        if isinstance(exc, AuthApiError) and exc.status < 500 and exc.status != 429:
            raise HTTPException(401, 'Could not sign in. Check your email and password, and confirm your email if needed.') from None
        raise auth_error(exc) from None
    if not result.session:
        raise HTTPException(401, 'Please confirm your email before signing in.')
    set_session_cookies(response, request, result.session)
    return {'signed_in': True}


@router.get('/me')
def me(response: Response, user=Depends(current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return public_account(user)


@router.post('/refresh')
def refresh(request: Request, response: Response, db: Client = Depends(get_auth_client)):
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(401, 'Please sign in to continue.')
    try:
        result = db.auth.refresh_session(refresh_token)
    except (AuthError, HTTPError) as exc:
        if isinstance(exc, AuthApiError) and exc.status < 500 and exc.status != 429:
            raise HTTPException(401, 'Please sign in again.') from None
        raise auth_error(exc) from None
    if not result.session:
        raise HTTPException(401, 'Please sign in again.')
    set_session_cookies(response, request, result.session)
    return {'signed_in': True}


@router.post('/logout')
def logout(request: Request, response: Response, db: Client = Depends(get_auth_client)):
    token = request.cookies.get(ACCESS_COOKIE)
    # Revocation is attempted with the current token; cookies are always removed.
    if token:
        try:
            db.auth.admin.sign_out(token, scope='local')
        except (AuthError, HTTPError):
            pass
    clear_session_cookies(response)
    return {'signed_in': False}
