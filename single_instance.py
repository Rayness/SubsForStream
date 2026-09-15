"""One running copy: a second launch wakes the first window and exits."""
import ctypes
import sys
import threading

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF


class SingleInstance:
    def __init__(self, name='Local\\SubForStream'):
        self.primary = True
        self._closed = False
        self._thread = None
        if sys.platform != 'win32':
            self._kernel = None
            return
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.restype = kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.SetEvent.argtypes = kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        self._kernel = kernel
        # The mutex lives as long as the process, so a crash never leaves a stale lock.
        self._mutex = kernel.CreateMutexW(None, False, name)
        self.primary = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        self._event = kernel.CreateEventW(None, False, False, name + '.show')

    def notify(self):
        """Ask the running copy to show its window."""
        if self._kernel:
            self._kernel.SetEvent(self._event)

    def listen(self, callback):
        if not self._kernel:
            return
        def wait():
            while self._kernel.WaitForSingleObject(self._event, INFINITE) == WAIT_OBJECT_0 and not self._closed:
                callback()
        self._thread = threading.Thread(target=wait, daemon=True)
        self._thread.start()

    def close(self):
        if not self._kernel or self._closed:
            return
        self._closed = True
        if self._thread:
            self._kernel.SetEvent(self._event)
            self._thread.join(1)
        self._kernel.CloseHandle(self._event)
        self._kernel.CloseHandle(self._mutex)
