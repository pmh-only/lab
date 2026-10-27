"""Non-secret native Seahub integration; credentials are supplied by Vault."""

import os


SERVICE_URL = "https://drive.pmh.codes"
FILE_SERVER_ROOT = SERVICE_URL + "/seafhttp"
TIME_ZONE = "Asia/Seoul"
CSRF_TRUSTED_ORIGINS = [SERVICE_URL]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CACHES = {
    "default": {"BACKEND": "django_pylibmc.memcached.PyLibMCCache", "LOCATION": "memcached:11211"},
    "locmem": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}
COMPRESS_CACHE_BACKEND = "locmem"
ENABLE_OAUTH = True
OAUTH_CREATE_UNKNOWN_USER = True
OAUTH_ACTIVATE_USER_AFTER_CREATION = True
OAUTH_ENABLE_INSECURE_TRANSPORT = False
OAUTH_CLIENT_ID = "lab-seafile"
OAUTH_CLIENT_SECRET = os.environ["OAUTH_CLIENT_SECRET"]
OAUTH_REDIRECT_URL = SERVICE_URL + "/oauth/callback/"
OAUTH_PROVIDER_DOMAIN = "auth.pmh.codes"
OAUTH_PROVIDER = "authentik"
OAUTH_AUTHORIZATION_URL = "https://auth.pmh.codes/application/o/authorize/"
OAUTH_TOKEN_URL = "https://auth.pmh.codes/application/o/token/"
OAUTH_USER_INFO_URL = "https://auth.pmh.codes/application/o/userinfo/"
OAUTH_SCOPE = ["openid", "email", "profile", "seafile"]
OAUTH_ATTRIBUTE_MAP = {
    "sub": (True, "uid"),
    "name": (False, "name"),
    "email": (False, "contact_email"),
    "seafile_role": (False, "role"),
}

# Custom roles inherit ordinary user permissions in native Seahub. Only this
# role receives a quota; default/guest roles and other users are unchanged.
ENABLED_ROLE_PERMISSIONS = {"discord_10gb": {"role_quota": "10g"}}
