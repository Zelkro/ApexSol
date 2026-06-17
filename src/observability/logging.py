import logging
import json
from datetime import datetime

class JsonFormatter(logging.Formatter):
    """
    Formats log records as structured JSON.
    Tracks trace context: event_id, mint, signature, bundle_id.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Capture trace context if passed via extra
        for field in ("event_id", "mint", "signature", "bundle_id"):
            if hasattr(record, field):
                log_data[field] = getattr(record, field)
                
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)

def setup_logging(level: str = "INFO"):
    logger = logging.getLogger("ApexSol")
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        
    # Set root level warning to avoid RPC noise
    logging.getLogger().setLevel(logging.WARNING)
    return logger
