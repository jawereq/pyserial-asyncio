from asyncio import CancelledError

from serial_asyncio import _BaseSerialTransport


class SerialTransport(_BaseSerialTransport):
    def __init__(self, loop, protocol, serial_instance):
        super().__init__(loop, protocol, serial_instance)
        self._write_task = None
        self._read_task = None
        self._reading_paused = False
        self._buffered_read_bytes = None
        self._loop.call_soon(self._start_read)

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
            # transport has been aborted or output flushed. If we're not closing, it's a flush.
            if not self._closing:
                self._write_buffer.clear()
                self._maybe_resume_protocol()
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

    def _start_read(self):
        assert self._read_task is None and self._buffered_read_bytes is None
        read_coro = self._loop.sock_recv(self._serial, self._max_read_size)
        self._read_task = self._loop.create_task(read_coro)
        self._read_task.add_done_callback(self._read_done)

    def _read_done(self, read_task):
        assert read_task == self._read_task
        self._read_task = None
        try:
            bytes_read = read_task.result()
        except CancelledError:
            assert self._closing  # transport closing or aborted
        except Exception as exc:
            self._fatal_error(exc, 'Fatal write error on serial transport')
        else:
            assert len(bytes_read) > 0
            assert not self._closing
            if not self._reading_paused:
                self._protocol.data_received(bytes_read)
            else:
                assert self._buffered_read_bytes is None
                self._buffered_read_bytes = bytes_read

    def _close(self, exc=None):
        self._closing = True
        if self._read_task:
            self._read_task.cancel()
        if self._flushed():
            assert self._write_task is None
            self._loop.call_soon(self._call_connection_lost, exc)

    def _abort(self, exc):
        self._closing = True
        if self._read_task is not None:
            self._read_task.cancel()
        if self._write_task is not None:
            self.write_task.cancel()
        self._loop.call_soon(self._call_connection_lost, exc)

    def flush(self):
        if self.write_task is not None:
            self._write_task.cancel()  # _write_done will finish the flush

    def pause_reading(self):
        self._reading_paused = True

    def resume_reading(self):
        if self._reading_paused:
            if not self._closing:
                if self._buffered_read_bytes is not None:
                    self._protocol.data_received(self._buffered_read_bytes)
                    self._buffered_read_bytes = None
                if self._read_task is None:
                    self._start_read()
            self._reading_paused = False
