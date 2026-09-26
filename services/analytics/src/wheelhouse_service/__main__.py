"""Start the service on loopback only."""

import logging

import uvicorn

from .settings import Settings


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(level=settings.log_level.upper(), format="%(message)s")
    uvicorn.run(
        "wheelhouse_service.http:create_app",
        factory=True,
        host="127.0.0.1",
        port=settings.port,
        log_level=settings.log_level,
        access_log=False,
    )


if __name__ == "__main__":
    main()
