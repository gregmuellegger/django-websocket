#encoding:utf-8
import os
import array
import logging
import struct
import select
import socket
import hashlib
import base64
from errno import EINTR


logger = logging.getLogger(__name__)


class BaseWebSocketProtocol(object):

    def __init__(self, request):
        self.request = request

    @property
    def sock(self):
        try:
            if 'gunicorn.socket' in self.request.META:
                sock = self.request.META['gunicorn.socket'].dup()
            else:
                wsgi_input = self.request.META['wsgi.input']
                if hasattr(wsgi_input, '_sock'):
                    sock = wsgi_input._sock
                elif hasattr(wsgi_input, 'rfile'):  # gevent
                    sock = wsgi_input.rfile._sock
                else:
                    raise ValueError('Socket not found in wsgi.input')
            return sock
        except AttributeError as e:
            logger.exception(e)
            return None


class WebSocketProtocol(BaseWebSocketProtocol):

    LENGTH_7 = 0x7d
    LENGTH_16 = 1 << 16
    LENGTH_63 = 1 << 63
    OPCODE_TEXT = 0x1
    OPCODE_BINARY = 0x2
    OPCODE_CLOSE = 0x8
    OPCODE_PING = 0x9
    OPCODE_PONG = 0xa
    STATUS_NORMAL = 1000
    STATUS_GOING_AWAY = 1001
    STATUS_PROTOCOL_ERROR = 1002
    STATUS_UNSUPPORTED_DATA_TYPE = 1003
    STATUS_STATUS_NOT_AVAILABLE = 1005
    STATUS_ABNORMAL_CLOSED = 1006
    STATUS_INVALID_PAYLOAD = 1007
    STATUS_POLICY_VIOLATION = 1008
    STATUS_MESSAGE_TOO_BIG = 1009
    STATUS_INVALID_EXTENSION = 1010
    STATUS_UNEXPECTED_CONDITION = 1011
    STATUS_TLS_HANDSHAKE_ERROR = 1015

    def __init__(self, request, mask_outgoing=False):
        BaseWebSocketProtocol.__init__(self, request)
        self.mask_outgoing = mask_outgoing
        self.closed = False

    def read(self):
        """
        Receive string data(byte array) from the server.

        return value: string(byte array) value.
        """
        try:
            _, data = self.read_data()
            return data
        except BaseException:
            self.abort()

    @classmethod
    def mask_or_unmask(cls, mask_key, data):
        """
        mask or unmask data. Just do xor for each byte

        mask_key: 4 byte string(byte).

        data: data to mask/unmask.
        """
        _m = array.array("B", mask_key)
        _d = array.array("B", data)
        for i in xrange(len(_d)):
            _d[i] ^= _m[i % 4]
        return _d.tostring()

    @classmethod
    def select_subprotocol(cls, subprotocols):
        pass

    @classmethod
    def compute_accept_value(cls, key):
        """Computes the value for the Sec-WebSocket-Accept header,
        given the value for Sec-WebSocket-Key.
        """
        sha1 = hashlib.sha1()
        sha1.update(key)
        sha1.update(b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11")  # Magic value
        return base64.b64encode(sha1.digest())

    def read_data(self):
        """
        Recieve data with operation code.

        return  value: tuple of operation code and string(byte array) value.
        """
        while not self.closed:
            fin, opcode, data = self.read_frame()
            if not fin and not opcode and not data:
                # handle error:
                # 'NoneType' object has no attribute 'opcode'
                raise ValueError(
                    "Not a valid fin %s opcode %s data %s" % (
                        fin, opcode, data
                    )
                )
            elif opcode in (
                self.OPCODE_TEXT,
                self.OPCODE_BINARY
            ):
                return (opcode, data)
            elif opcode == self.OPCODE_CLOSE:
                self.write_close()
                self.abort()
                return (opcode, None)
            elif opcode == self.OPCODE_PING:
                self.write_pong(data)

    def read_frame(self):
        """
        recieve data as frame from server.
        """
        header_bytes = self._read_strict(2)
        if not header_bytes:
            return None, None, None
        b1 = ord(header_bytes[0])
        fin = b1 >> 7 & 1
        opcode = b1 & 0xf
        b2 = ord(header_bytes[1])
        mask = b2 >> 7 & 1
        length = b2 & 0x7f

        length_data = ""
        if length == 0x7e:
            length_data = self._read_strict(2)
            length = struct.unpack("!H", length_data)[0]
        elif length == 0x7f:
            length_data = self._read_strict(8)
            length = struct.unpack("!Q", length_data)[0]
        mask_key = ""
        if mask:
            mask_key = self._read_strict(4)
        data = self._read_strict(length)
        if mask:
            data = self.mask_or_unmask(mask_key, data)
        return fin, opcode, data

    def _read_strict(self, bufsize):
        remaining = bufsize
        _bytes = ""
        while remaining:
            _buffer = self.sock.recv(bufsize)
            if not _buffer:
                raise socket.error('socket closed')
            _bytes += _buffer
            remaining = bufsize - len(_bytes)

        return _bytes

    def accept_connection(self):
        try:
            fields = ("HTTP_SEC_WEBSOCKET_KEY", "HTTP_SEC_WEBSOCKET_VERSION")
            if not all(map(self.request.META.get, fields)):
                raise ValueError("Missing/Invalid WebSocket headers")

            subprotocol_header = ''
            subprotocols = self.request.META.get(
                "HTTP_SEC_WEBSOCKET_PROTOCOL", '')
            subprotocols = [s.strip() for s in subprotocols.split(',')]
            if subprotocols:
                selected = self.select_subprotocol(subprotocols)
                if selected:
                    assert selected in subprotocols
                    subprotocol_header = (
                        "Sec-WebSocket-Protocol: %s\r\n" % selected
                    )
            accept_header = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: %s\r\n"
                "%s"
                "\r\n" % (
                    self.compute_accept_value(
                        self.request.META.get("HTTP_SEC_WEBSOCKET_KEY")
                    ),
                    subprotocol_header
                )
            )
            self.sock.send(accept_header)
        except BaseException:
            self.abort()

    def can_read(self, timeout=0.0):
        '''
        Return ``True`` if new data can be read from the socket.
        '''
        r, w, e = [self.sock], [], []
        try:
            r, w, e = select.select(r, w, e, timeout)
        except select.error as err:
            if err.args[0] == EINTR:
                return False
            raise err
        return self.sock in r

    def _write_frame(self, fin, opcode, data):
        if fin:
            finbit = 0x80
        else:
            finbit = 0
        frame = struct.pack("B", finbit | opcode)
        l = len(data)
        if self.mask_outgoing:
            mask_bit = 0x80
        else:
            mask_bit = 0
        if l < 126:
            frame += struct.pack("B", l | mask_bit)
        elif l <= 0xFFFF:
            frame += struct.pack("!BH", 126 | mask_bit, l)
        else:
            frame += struct.pack("!BQ", 127 | mask_bit, l)
        if self.mask_outgoing:
            mask = os.urandom(4)
            data = mask + self._apply_mask(mask, data)
        frame += data
        self.sock.send(frame)

    def write(self, message, binary=False):
        """Sends the given message to the client of this Web Socket."""
        if binary:
            opcode = 0x2
        else:
            opcode = 0x1
        message = message.encode('utf8')
        try:
            self._write_frame(True, opcode, message)
        except IOError as e:
            logger.debug(e)
            self.abort()

    def write_ping(self, payload=""):
        """
        write ping data.

        payload: data payload to write server.
        """
        self.write(payload, self.OPCODE_PING)

    def write_pong(self, data):
        """
        write pong data.

        payload: data payload to write server.
        """
        self.write(data, self.OPCODE_PONG)

    def write_close(self, reason=b""):
        """
        write close data to the server.
        reason: the reason to close. This must be string.
        """
        self._write_frame(True, 0x8, reason)

    def abort(self):
        """Instantly aborts the WebSocket connection by closing the socket"""
        self.closed = True
        self.sock.close()  # forcibly tear down the connection

    def close(self):
        if not self.closed:
            self.write_close()
            self.abort()
