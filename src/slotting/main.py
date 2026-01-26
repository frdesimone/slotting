import logging
from .config import get_settings
from .logging_config import configure_logging

logger = logging.getLogger("slotting")

def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    logger.info("Arrancando slotting (env=%s)", settings.env)
    return 0
