from asyncio import CancelledError

from serial_asyncio import _BaseSerialTransport


class SerialTransport(_BaseSerialTransport):
    def __init__(self, loop, protocol, serial_instance):
        super().__init__(loop, protocol, serial_instance)
        self._write_task = None

    def _ensure_writer(self):
        if self._write_task is None and not self._closing and len(self._write_buffer) > 0:
            write_coro = self._loop.sock_sendall(self._serial, self._write_buffer[0])
            self._write_task = self._loop.create_task(write_coro)
            self._write_task.add_done_callback(self._write_done)

    def _write_done(self, write_task):
        assert write_task == self._write_task
        self._write_task = None
        try:
            n_bytes_written = write_task.result()
        except CancelledError:
            assert self._closing
        except Exception as exc:
            self._fatal_error(exc, 'Fatal write error on serial transport')
        else:
            assert n_bytes_written == len(self._write_buffer[0])
        finally:
            self._write_buffer.popleft()
            self._ensure_writer()
