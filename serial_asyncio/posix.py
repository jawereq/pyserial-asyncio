
class SerialTransport(_BaseSerialTransport):
    def __init__(self, loop, protocol, serial_instance):
        super().__init__(loop, protocol, serial_instance)
        self._has_reader = False
        self._has_writer = False

        # Asynchronous I/O requires non-blocking devices
        self._serial.timeout = 0
        self._serial.write_timeout = 0
        
        loop.call_soon(self._ensure_reader)

    def _read_ready(self):
        try:
            data = self._serial.read(self._max_read_size)
        except serial.SerialException as e:
            self._close(exc=e)
        else:
            if data:
                self._protocol.data_received(data)

    def _ensure_writer(self):
        if (not self._has_writer) and (not self._closing):
            self._loop.add_writer(self._serial.fileno(), self._write_ready)
            self._has_writer = True

    def _write_ready(self):
        """Asynchronously write buffered data.

        This method is called back asynchronously as a writer
        registered with the asyncio event-loop against the
        underlying file descriptor for the serial port.

        Should the write-buffer become empty if this method
        is invoked while the transport is closing, the protocol's
        connection_lost() method will be called with None as its
        argument.
        """
        data = b''.join(self._write_buffer)
        assert data, 'Write buffer should not be empty'

        self._write_buffer.clear()

        try:
            n = self._serial.write(data)
        except (BlockingIOError, InterruptedError):
            self._write_buffer.append(data)
        except serial.SerialException as exc:
            self._fatal_error(exc, 'Fatal write error on serial transport')
        else:
            if n == len(data):
                assert self._flushed()
                self._remove_writer()
                self._maybe_resume_protocol()  # May cause further writes
                # _write_ready may have been invoked by the event loop
                # after the transport was closed, as part of the ongoing
                # process of flushing buffered data. If the buffer
                # is now empty, we can close the connection
                if self._closing and self._flushed():
                    self._close()
                return

            assert 0 <= n < len(data)
            data = data[n:]
            self._write_buffer.append(data)  # Try again later
            self._maybe_resume_protocol()
            assert self._has_writer

    def _close(self, exc=None):
        self._closing = True
        self._remove_reader()
        if self._flushed():
            self._remove_writer()
            self._loop.call_soon(self._call_connection_lost, exc)

    def _abort(self, exc):
        self._closing = True
        self._remove_reader()
        self._remove_writer()  # Pending buffered data will not be written
        self._loop.call_soon(self._call_connection_lost, exc)

    def flush(self):
        self._remove_writer()
        self._write_buffer.clear()
        self._maybe_resume_protocol()

    def _ensure_reader(self):
        if (not self._has_reader) and (not self._closing):
            self._loop.add_reader(self._serial.fileno(), self._read_ready)
            self._has_reader = True

    def _remove_reader(self):
        if self._has_reader:
            self._loop.remove_reader(self._serial.fileno())
            self._has_reader = False


    def _remove_writer(self):
        if self._has_writer:
            self._loop.remove_writer(self._serial.fileno())
            self._has_writer = False

    def pause_reading(self):
        self._remove_reader()

    def resume_reading(self):
        self._ensure_reader()
