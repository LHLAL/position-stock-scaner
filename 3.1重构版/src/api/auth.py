"""
Authentication middleware and decorator for Flask routes.
"""

from flask import request, jsonify
from functools import wraps

from src.config import settings


def check_auth_config():
    """
    检查鉴权配置
    Returns:
        tuple: (enabled: bool, config: dict)
    """
    if not settings.get('web_auth.enabled', False):
        return False, {}
    return True, settings.get('web_auth', {})


def require_auth(f):
    """
    鉴权装饰器 - 支持session和Bearer Token两种认证方式

    支持格式:
    - Authorization: Bearer <password>
    - Authorization: <password>
    - Session-based authentication (session['authenticated'] == True)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_enabled, auth_config = check_auth_config()

        # Auth disabled - allow access
        if not auth_enabled:
            return f(*args, **kwargs)

        # Check session-based authentication first
        from flask import session
        if session.get('authenticated'):
            login_time = session.get('login_time')
            if login_time:
                session_timeout = auth_config.get('session_timeout', 3600)
                from datetime import datetime
                if (datetime.now() - datetime.fromisoformat(login_time)).total_seconds() < session_timeout:
                    return f(*args, **kwargs)
                else:
                    session.pop('authenticated', None)
                    session.pop('login_time', None)

        # Check Authorization header (Bearer token or basic auth)
        auth = request.authorization
        if auth and auth.password == auth_config.get('password'):
            return f(*args, **kwargs)

        # Auth failed - return 401
        return jsonify({'error': 'Unauthorized'}), 401

    return decorated_function