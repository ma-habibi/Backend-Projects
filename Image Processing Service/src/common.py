import pathlib
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv


class Common:
    def __init__(self):
        self._base_dir = pathlib.Path(__file__).resolve().parent.parent
        load_dotenv(self._base_dir / ".env")
        self.logger = self._set_logger()

    @staticmethod
    def _set_logger() -> logging.Logger:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "app.log"
        logger = logging.getLogger("app")
        logger.setLevel(logging.DEBUG)

        if not logger.handlers:
            formatter = logging.Formatter(
                "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s"
            )

            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)

            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)

            logger.addHandler(console_handler)
            logger.addHandler(file_handler)

            logger.propagate = False
        return logger

    def get_logger(self) -> logging.Logger:
        """
        The getter method for the logger.

        Returns:
            logging.Logger: The logger instance.
        """
        return self.logger

    def get_base_dir(self) -> pathlib.Path:
        """
        The getter method for the base_dir.

        Returns:
            pathlib.Path: The base_dir instance.
        """
        return self._base_dir


common = Common()
