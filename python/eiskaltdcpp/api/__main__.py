"""
CLI entry point for the eiskaltdcpp-py REST API server.

Run with:
    python -m eiskaltdcpp.api --help
    python -m eiskaltdcpp.api --admin-user admin --admin-pass secret
    python -m eiskaltdcpp.api --port 8080 --host 0.0.0.0

Environment variables:
    EISKALTDCPP_ADMIN_USER  — Admin username (default: admin)
    EISKALTDCPP_ADMIN_PASS  — Admin password (required if not set via CLI)
    EISKALTDCPP_JWT_SECRET  — JWT signing secret (auto-generated if not set)
    EISKALTDCPP_CONFIG_DIR  — DC client config directory
    EISKALTDCPP_USERS_FILE  — Path to persist API users (JSON)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

import uvicorn


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="eiskaltdcpp-api",
        description="REST API server for eiskaltdcpp-py DC client",
    )

    # Server options
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="Bind port (default: 8080)",
    )

    # Auth options
    parser.add_argument(
        "--admin-user",
        default=os.environ.get("EISKALTDCPP_ADMIN_USER", "admin"),
        help="Initial admin username (env: EISKALTDCPP_ADMIN_USER)",
    )
    parser.add_argument(
        "--admin-pass",
        default=os.environ.get("EISKALTDCPP_ADMIN_PASS"),
        help="Initial admin password (env: EISKALTDCPP_ADMIN_PASS)",
    )
    parser.add_argument(
        "--jwt-secret",
        default=os.environ.get("EISKALTDCPP_JWT_SECRET"),
        help="JWT signing secret (env: EISKALTDCPP_JWT_SECRET)",
    )
    parser.add_argument(
        "--token-expire-minutes", type=int, default=1440,
        help="JWT token lifetime in minutes (default: 1440 = 24h)",
    )
    parser.add_argument(
        "--users-file",
        default=os.environ.get("EISKALTDCPP_USERS_FILE"),
        help="Path to persist API users JSON (env: EISKALTDCPP_USERS_FILE)",
    )

    # DC client options
    parser.add_argument(
        "--config-dir",
        default=os.environ.get("EISKALTDCPP_CONFIG_DIR", ""),
        help="DC client config directory (env: EISKALTDCPP_CONFIG_DIR)",
    )
    parser.add_argument(
        "--no-dc-client", action="store_true",
        help="Run API server without DC client (auth-only mode)",
    )

    # CORS
    parser.add_argument(
        "--cors-origin", action="append", dest="cors_origins",
        help="Allowed CORS origins (can be specified multiple times)",
    )

    # Logging
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Main entry point."""
    args = parse_args(argv)

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("eiskaltdcpp.api")

    # Import here to avoid circular issues
    from eiskaltdcpp.api.app import create_app

    # Optionally create DC client
    dc_client = None
    if not args.no_dc_client:
        try:
            from eiskaltdcpp import AsyncDCClient
            dc_client = AsyncDCClient(args.config_dir)
            logger.info("DC client created with config dir: %s",
                        args.config_dir or "(default)")
        except ImportError:
            logger.warning(
                "SWIG module not available — running in auth-only mode"
            )

    # Create app
    app = create_app(
        dc_client=dc_client,
        admin_username=args.admin_user,
        admin_password=args.admin_pass,
        jwt_secret=args.jwt_secret,
        token_expire_minutes=args.token_expire_minutes,
        users_file=args.users_file,
        cors_origins=args.cors_origins,
    )

    logger.info("Starting API server on %s:%d", args.host, args.port)

    # Run with uvicorn
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level.lower(),
    )


if __name__ == "__main__":
    main()
