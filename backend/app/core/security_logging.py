"""Remove admission credentials from Uvicorn HTTP and WebSocket log records."""
import logging
import re

_CREDENTIAL = re.compile(r'([?&](?:ticket|code|token|access_token|participant_token)=)[^&\s"\']+', re.IGNORECASE)


class CredentialRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Preserve the positional access-log tuple: Uvicorn's AccessFormatter
        # unpacks its five fields rather than just calling getMessage().
        def redact(value):
            return _CREDENTIAL.sub(r'\1[redacted]', value) if isinstance(value, str) else value
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


def configure_security_logging() -> None:
    for name in ('uvicorn.access', 'uvicorn.error'):
        logger = logging.getLogger(name)
        if not any(isinstance(item, CredentialRedactionFilter) for item in logger.filters):
            logger.addFilter(CredentialRedactionFilter())
