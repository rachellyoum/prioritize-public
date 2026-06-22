# src/user_service/bridge.py


def get_user_repository():
    from user_service.api import get_user_repository as _repo
    return _repo()
