"""
eiskaltdcpp-py REST API package.

Provides a FastAPI-based REST API for controlling a running DC client
instance with JWT authentication and role-based access control.
"""
from eiskaltdcpp.api.app import create_app

__all__ = ["create_app"]
