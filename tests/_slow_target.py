"""A worker target that never finishes, used to test that stuck workers are killed.

It lives in its own module so the spawned worker process can import it by name.
"""

import time


def sleep_forever(path: str, block: object) -> None:
    time.sleep(120)
