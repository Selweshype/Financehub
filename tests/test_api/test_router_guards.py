"""Every router except `auth` must reject unauthenticated requests.

This is parametrised over the live router modules rather than a hand-written
list, so a new router that ships without `require_session` fails this test
instead of silently exposing data.
"""

import importlib
import pkgutil

import pytest
from fastapi import Depends

import app.routers as routers_pkg
from app.security.session import require_session

# /auth is the login surface and is deliberately reachable while logged out.
UNGUARDED_BY_DESIGN = {"auth"}


def _router_modules():
    names = []
    for mod in pkgutil.iter_modules(routers_pkg.__path__):
        if mod.name.startswith("_"):
            continue
        names.append(mod.name)
    return sorted(names)


@pytest.mark.parametrize("module_name", _router_modules())
def test_router_requires_session(module_name):
    """Each router declares require_session as a router-level dependency."""
    if module_name in UNGUARDED_BY_DESIGN:
        pytest.skip(f"{module_name} is intentionally reachable while logged out")

    module = importlib.import_module(f"app.routers.{module_name}")
    router = getattr(module, "router", None)
    assert router is not None, f"app.routers.{module_name} has no `router`"

    depends_type = type(Depends(lambda: None))
    dependency_calls = [
        dep.dependency for dep in router.dependencies if isinstance(dep, depends_type)
    ]
    assert require_session in dependency_calls, (
        f"app.routers.{module_name} does not carry require_session at router level — "
        "every data-bearing router must be guarded."
    )


def test_auth_router_is_the_only_exception():
    """Keeps the allowlist honest if routers are renamed or added."""
    assert UNGUARDED_BY_DESIGN <= set(_router_modules())
