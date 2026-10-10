"""Process locks for capture startup and ownership; contains no user data."""
import os
import time


class CaptureLock:
    def __init__(self, path, timeout=0):
        self.path, self.timeout, self.stream = path, timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open('a+b')
        # Windows byte locks can extend past EOF; reading a held region is denied.
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.stream = stream
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    stream.close()
                    raise ValueError('已有采集实例正在启动或运行。') from None
                time.sleep(.1)

    def __exit__(self, *args):
        if self.stream is None:
            return
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None
