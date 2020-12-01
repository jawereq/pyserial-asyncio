from asyncio import CancelledError

from serial_asyncio import _BaseSerialTransport


class SerialTransport(_BaseSerialTransport):
    def __init__(self, loop, protocol, serial_instance):
        super().__init__(loop, protocol, serial_instance)
        self._write_task = None
        self._read_task = None
        self._reading_paused = False
        self._buffered_read_bytes = None

    def _ensure_writer(self):
        if self._write_task is None and len(self._write_buffer) > 0:
            write_coro = self._loop.sock_sendall(self._serial, self._write_buffer[0])
            self._write_task = self._loop.create_task(write_coro)
            self._write_task.add_done_callback(self._write_done)

    def _write_done(self, write_task):
        assert write_task == self._write_task
        self._write_task = None
        written_bytes = self._write_buffer.popleft()
        try:
            n_bytes_written = write_task.result()
        except CancelledError:
            assert self._closing  # transport has been aborted or output flushed
        except Exception as exc:
            self._fatal_error(exc, 'Fatal write error on serial transport')
        else:
            assert n_bytes_written == len(written_bytes)

            if self._closing:
                if self._flushed() and self._read_task is None:
                    self._loop.call_soon(self._call_connection_lost, None)
            else:
                self._maybe_resume_protocol()
            self._ensure_writer()

    def _close(self, exc=None):
        """Close the transport gracefully.

        If the write buffer is already empty, writing will be
        stopped immediately and a call to the protocol's
        connection_lost() method scheduled.

        If the write buffer is not already empty, the
        asynchronous writing will continue, and the _write_ready
        method will call this _close method again when the
        buffer has been flushed completely.
        """
        self._closing = True
        if self._read_task:
            self._read_task.cancel()
        elif self._flushed():
            assert self._write_task is None
            self._loop.call_soon(self._call_connection_lost, exc)

    def pause_reading(self):
        self._reading_paused = True

    def resume_reading(self):
        if self._reading_paused:
            if not self._closing:
                pass
            self._reading_paused = False
