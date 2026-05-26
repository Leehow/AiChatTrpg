import logging

import uvicorn

from core.config import get_settings


def main() -> None:
    settings = get_settings()
    # Surface application loggers (chatrpg.*, agents.trpg.*) at the configured
    # level. Without this, Python's root logger sits at WARNING and INFO/DEBUG
    # messages from app code never reach the uvicorn-captured stream.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(name)s [%(levelname)s] %(message)s",
    )
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
