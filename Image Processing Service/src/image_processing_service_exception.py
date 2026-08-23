class ImageProcessingServiceException(Exception):
    """
    Raised for any ImageProcessingService failure: invalid credentials,
    duplicate usernames, missing/unauthorized resources, or invalid input.

    Attributes:
        status_code (int): The HTTP status code server.py's exception
            handler should respond with. Defaults to 400.
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code
