import logging
import sys

def setup_logger(name: str = "MMCoin") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Standard format for high frequency logs showing microsecond time precision
    formatter = logging.Formatter(
        '%(asctime)s.%(msecs)03d | %(levelname)s | [%(name)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)
    
    return logger
