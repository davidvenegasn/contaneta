"""Auth router package — aggregates all auth submodules."""
from fastapi import APIRouter

from routers.auth.login import register_login_routes
from routers.auth.register import register_register_routes
from routers.auth.password import register_password_routes
from routers.auth.oauth import register_oauth_routes
from routers.auth.onboarding import register_onboarding_routes


def get_auth_router(templates):
    """Build the auth router with login, signup, OAuth, onboarding, and password routes."""
    router = APIRouter(tags=["auth"])

    register_login_routes(router, templates)
    register_register_routes(router, templates)
    register_password_routes(router, templates)
    register_oauth_routes(router, templates)
    register_onboarding_routes(router, templates)

    return router
