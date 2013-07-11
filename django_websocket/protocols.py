#encoding:utf-8
import os
import array
import logging
import struct
import select
import socket
from errno import EINTR


logger = logging.getLogger(__name__)


class ABNF(object):
    
    """
    ABNF frame class.
    see http://tools.ietf.org/html/rfc5234
    and http://tools.ietf.org/html/rfc6455#section-5.2
    """

    # operation code values.
    OPCODE_TEXT = 0x1
    OPCODE_BINARY = 0x2
    OPCODE_CLOSE = 0x8
    OPCODE_PING = 0x9
    OPCODE_PONG = 0xa

    # available operation code value tuple
    OPCODES = (
        OPCODE_TEXT,
        OPCODE_BINARY,
        OPCODE_CLOSE,
        OPCODE_PING,
        OPCODE_PONG
    )

    # opcode human readable string
    OPCODE_MAP = {
        OPCODE_TEXT: "text",
        OPCODE_BINARY: "binary",
        OPCODE_CLOSE: "close",
        OPCODE_PING: "ping",
        OPCODE_PONG: "pong"
    }

    # data length threashold.
    LENGTH_7 = 0x7d
    LENGTH_16 = 1 << 16
    LENGTH_63 = 1 << 63
    get_mask_key = os.urandom

    def __init__(self, fin=0, rsv1=0, rsv2=0, rsv3=0,
                 opcode=OPCODE_TEXT, mask=1, data=""):
        """
        Constructor for ABNF.
        please check RFC for arguments.
        """
        self.fin = fin
        self.rsv1 = rsv1
        self.rsv2 = rsv2
        self.rsv3 = rsv3
        self.opcode = opcode
        self.mask = mask
        self.data = data

    @staticmethod
    def create_frame(data, opcode):
        """
        create frame to send text, binary and other data.

        data: data to send. This is string value(byte array).
            if opcode is OPCODE_TEXT and this value is uniocde,
            data value is conveted into unicode string, automatically.
        """
        if opcode == ABNF.OPCODE_TEXT and isinstance(data, unicode):
            data = data.encode("utf-8")
        # mask must be set if send data from client
        return ABNF(1, 0, 0, 0, opcode, 1, data)

    def format(self):
        """
        format this object to string(byte array) to send data to server.
        """
        if not self._is_bool(self.fin, self.rsv1, self.rsv2, self.rsv3):
            raise ValueError("not 0 or 1")
        if self.opcode not in ABNF.OPCODES:
            raise ValueError("Invalid OPCODE")
        length = len(self.data)
        if length >= ABNF.LENGTH_63:
            raise ValueError("data is too long")

        frame_header = chr(self.fin << 7
                           | self.rsv1 << 6 | self.rsv2 << 5 | self.rsv3 << 4
                           | self.opcode)
        if length < ABNF.LENGTH_7:
            frame_header += chr(self.mask << 7 | length)
        elif length < ABNF.LENGTH_16:
            frame_header += chr(self.mask << 7 | 0x7e)
            frame_header += struct.pack("!H", length)
        else:
            frame_header += chr(self.mask << 7 | 0x7f)
            frame_header += struct.pack("!Q", length)

        if not self.mask:
            return frame_header + self.data
        else:
            mask_key = self.get_mask_key(4)
            return frame_header + self._get_masked(mask_key)

    def _get_masked(self, mask_key):
        s = ABNF.create_mask(mask_key, self.data)
        return mask_key + "".join(s)

    @classmethod
    def _is_bool(cls, *values):
        for v in values:
            if v not in (0, 1):
                return False
        return True

    @staticmethod
    def create_mask(mask_key, data):
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


class WebSocketProtocol(object):

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

    def __init__(self, sock, handshake_reply=None, get_mask_key=None):
        self.sock = sock
        self.closed = False
        self.get_mask_key = get_mask_key
        self.handshake_reply = handshake_reply

    def send(self, payload, opcode=ABNF.OPCODE_TEXT):
        """
        Send the data as string.

        payload: Payload must be utf-8 string or unicoce,
                  if the opcode is OPCODE_TEXT.
                  Otherwise, it must be string(byte array)
        """
        frame = ABNF.create_frame(payload, opcode)
        if self.get_mask_key:
            frame.get_mask_key = self.get_mask_key
        data = frame.format()
        while data:
            l = self.sock.send(data)
            data = data[l:]

    def recv(self):
        """
        Receive string data(byte array) from the server.

        return value: string(byte array) value.
        """
        _, data = self.recv_data()
        return data

    def ping(self, payload=""):
        """
        send ping data.

        payload: data payload to send server.
        """
        self.send(payload, ABNF.OPCODE_PING)

    def pong(self, payload):
        """
        send pong data.

        payload: data payload to send server.
        """
        self.send(payload, ABNF.OPCODE_PONG)

    def recv_data(self):
        """
        Recieve data with operation code.

        return  value: tuple of operation code and string(byte array) value.
        """
        while True:
            frame = self.recv_frame()
            if not frame:
                # handle error:
                # 'NoneType' object has no attribute 'opcode'
                raise ValueError("Not a valid frame %s" % frame)
            elif frame.opcode in (
                ABNF.OPCODE_TEXT,
                ABNF.OPCODE_BINARY
            ):
                return (frame.opcode, frame.data)
            elif frame.opcode == ABNF.OPCODE_CLOSE:
                self.close()
                return (frame.opcode, None)
            elif frame.opcode == ABNF.OPCODE_PING:
                self.pong(frame.data)

    def recv_frame(self):
        """
        recieve data as frame from server.

        return value: ABNF frame object.
        """
        header_bytes = self._recv_strict(2)
        if not header_bytes:
            return None
        b1 = ord(header_bytes[0])
        fin = b1 >> 7 & 1
        rsv1 = b1 >> 6 & 1
        rsv2 = b1 >> 5 & 1
        rsv3 = b1 >> 4 & 1
        opcode = b1 & 0xf
        b2 = ord(header_bytes[1])
        mask = b2 >> 7 & 1
        length = b2 & 0x7f

        length_data = ""
        if length == 0x7e:
            length_data = self._recv_strict(2)
            length = struct.unpack("!H", length_data)[0]
        elif length == 0x7f:
            length_data = self._recv_strict(8)
            length = struct.unpack("!Q", length_data)[0]

        mask_key = ""
        if mask:
            mask_key = self._recv_strict(4)
        data = self._recv_strict(length)
        if mask:
            data = ABNF.create_mask(mask_key, data)

        frame = ABNF(fin, rsv1, rsv2, rsv3, opcode, mask, data)
        return frame

    def _recv(self, bufsize):
        _bytes = self.sock.recv(bufsize)
        if not _bytes:
            raise socket.error('socket closed')
        return _bytes

    def _recv_strict(self, bufsize):
        remaining = bufsize
        _bytes = ""
        while remaining:
            _bytes += self._recv(remaining)
            remaining = bufsize - len(_bytes)

        return _bytes

    def send_close(self, status=STATUS_NORMAL, reason=""):
        """
        send close data to the server.
        reason: the reason to close. This must be string.
        """
        if status < 0 or status >= ABNF.LENGTH_16:
            raise ValueError("code is invalid range")
        self.send(struct.pack('!H', status) + reason, ABNF.OPCODE_CLOSE)

    def send_handshake_replay(self):
        if self.handshake_reply:
            self.sock.sendall(self.handshake_reply)

    def can_recv(self, timeout=0.0):
        '''
        Return ``True`` if new data can be read from the socket.
        '''
        r, w, e = [self.sock], [], []
        try:
            r, w, e = select.select(r, w, e, timeout)
        except select.error, err:
            if err.args[0] == EINTR:
                return False
            raise
        return self.sock in r

    def close(self):
        self.closed = True
        self.sock.close()
