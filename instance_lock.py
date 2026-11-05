"""Exclusive process lock on Windows and POSIX. OS releases it after a crash."""
import os

class InstanceLock:
    def __init__(self, path, platform=None):
        self.platform=platform or os.name
        self.file=open(path,'a+b')
        try:
            if self.platform=='nt':
                import msvcrt
                if os.fstat(self.file.fileno()).st_size==0:
                    self.file.write(b'\0'); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:
            self.file.close()
            raise

    def close(self):
        if self.file.closed: return
        try:
            if self.platform=='nt':
                import msvcrt
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
        finally: self.file.close()
