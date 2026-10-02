"""Verified Supabase accounts and HttpOnly browser sessions."""
from fastapi import Depends, HTTPException, Request, Response
from httpx import HTTPError
from supabase import Client, ClientOptions, create_client
from supabase_auth.errors import AuthApiError, AuthError

from app.config import Settings, get_settings

ACCESS_COOKIE = 'fh_access'
REFRESH_COOKIE = 'fh_refresh'


def get_auth_client(settings: Settings = Depends(get_settings)) -> Client:
    if not settings.supabase_url or not settings.supabase_key.get_secret_value():
        raise HTTPException(503, 'Account sign-in is temporarily unavailable.')
    return create_client(settings.supabase_url, settings.supabase_key.get_secret_value(),
                         options=ClientOptions(auto_refresh_token=False, persist_session=False))


def require_browser_request(request: Request, settings: Settings = Depends(get_settings)):
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return
    if request.headers.get('X-Fieldhouse-Request') != '1' or request.headers.get('Sec-Fetch-Site') == 'cross-site':
        raise HTTPException(403, 'Please submit this request from the Fieldhouse website.')
    origin = request.headers.get('origin')
    allowed = {str(request.base_url).rstrip('/'), settings.site_url.rstrip('/')}
    if origin and origin not in allowed:
        raise HTTPException(403, 'This request is not allowed.')


def set_session_cookies(response: Response, request: Request, session):
    secure = request.url.hostname not in ('localhost', '127.0.0.1', 'testserver')
    response.set_cookie(ACCESS_COOKIE, session.access_token, max_age=session.expires_in,
                        httponly=True, secure=secure, samesite='lax', path='/')
    response.set_cookie(REFRESH_COOKIE, session.refresh_token, max_age=60 * 60 * 24 * 14,
                        httponly=True, secure=secure, samesite='lax', path='/api/auth')
    response.headers['Cache-Control'] = 'no-store'


def clear_session_cookies(response: Response):
    response.delete_cookie(ACCESS_COOKIE, path='/')
    response.delete_cookie(REFRESH_COOKIE, path='/api/auth')
    response.headers['Cache-Control'] = 'no-store'


def current_user(request: Request, db: Client = Depends(get_auth_client)):
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(401, 'Please sign in to continue.')
    try:
        result = db.auth.get_user(token)
    except AuthApiError as exc:
        if exc.status >= 500:
            raise HTTPException(503, 'Account verification is temporarily unavailable.') from None
        raise HTTPException(401, 'Your session has expired. Please sign in again.') from None
    except (AuthError, HTTPError):
        raise HTTPException(503, 'Account verification is temporarily unavailable.') from None
    if not result or not result.user:
        raise HTTPException(401, 'Please sign in to continue.')
    return result.user


def is_admin(user) -> bool:
    # user_metadata is user-editable and must never authorize staff access.
    return user.app_metadata.get('role') == 'admin' and bool(user.email_confirmed_at)


def public_account(user) -> dict:
    return {'email': user.email, 'name': user.user_metadata.get('name', ''), 'is_admin': is_admin(user)}


def require_staff(user=Depends(current_user), _=Depends(require_browser_request)):
    if not is_admin(user):
        raise HTTPException(403, 'An administrator account is required.')
    return user
