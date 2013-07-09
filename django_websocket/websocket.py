import collections
import base64
import select
import string
import struct
from hashlib import md5,sha1
from errno import EINTR
from socket import error as SocketError


class MalformedWebSocket(ValueError):
    pass


def _extract_number(value):
    """
    Utility function which, given a string like 'g98sd  5[]221@1', will
    return 4926105. Used to parse the Sec-WebSocket-Key headers.

    In other words, it extracts digits from a string and returns the number
    due to the number of spaces.
    """
    out = ""
    spaces = 0
    for char in value:
        if char in string.digits:
            out += char
        elif char == " ":
            spaces += 1
    return int(out) / spaces

def is_websocket(request):
    """check the websocket"""
    if request.META.get('HTTP_CONNECTION', "").lower() == 'upgrade' and \
        request.META.get('HTTP_UPGRADE', "").lower() == 'websocket':
        return True
    else:
        return False

def get_websocket_version(request):
    if 'HTTP_SEC_WEBSOCKET_KEY1' in request.META:
        protocol_version = 76
        if 'HTTP_SEC_WEBSOCKET_KEY2' not in request.META:
            raise MalformedWebSocket()
    elif 'HTTP_SEC_WEBSOCKET_KEY' in request.META:
        protocol_version = 13
    else:
        protocol_version = 75
    return protocol_version

def make_version_76_handshake_replay(request):
    location = 'ws://%s%s' % (request.get_host(), request.path)
    qs = request.META.get('QUERY_STRING')
    if qs:location += '?' + qs
    key1 = _extract_number(request.META['HTTP_SEC_WEBSOCKET_KEY1'])
    key2 = _extract_number(request.META['HTTP_SEC_WEBSOCKET_KEY2'])
    # There's no content-length header in the request, but it has 8
    # bytes of data.
    key3 = request.META['wsgi.input'].read(8)
    key = struct.pack(">II", key1, key2) + key3
    handshake_response = md5(key).digest()
    handshake_reply = (
        "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
        "Upgrade: WebSocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Origin: %s\r\n"
        "Sec-WebSocket-Protocol: %s\r\n"
        "Sec-WebSocket-Location: %s\r\n" % (
            request.META.get('HTTP_ORIGIN'),
            request.META.get('HTTP_SEC_WEBSOCKET_PROTOCOL', 'default'),
            location))
    handshake_reply = str(handshake_reply)
    handshake_reply = '%s\r\n%s' % (handshake_reply, handshake_response)
    return handshake_reply

def make_version_75_handshake_replay(request):
    location = 'ws://%s%s' % (request.get_host(), request.path)
    qs = request.META.get('QUERY_STRING')
    if qs:location += '?' + qs
    handshake_reply = (
    "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
    "Upgrade: WebSocket\r\n"
    "Connection: Upgrade\r\n"
    "WebSocket-Origin: %s\r\n"
    "WebSocket-Location: %s\r\n\r\n" % (
        request.META.get('HTTP_ORIGIN'),
        location))
    return handshake_reply

def make_version_rfc6455_handshake_replay(request):
    location = 'ws://%s%s' % (request.get_host(), request.path)
    qs = request.META.get('QUERY_STRING')
    if qs:location += '?' + qs
    key = request.META['HTTP_SEC_WEBSOCKET_KEY']
    #Create hand shake response for that is after version 07
    handshake_response = base64.b64encode(sha1(key.encode("utf-8")+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode("utf-8")).digest())
    handshake_reply = (
    "HTTP/1.1 101 Switching Protocols\r\n"
    "Upgrade: websocket\r\n"
    "Connection: Upgrade\r\n"
    "Sec-WebSocket-Accept: %s\r\n\r\n" % handshake_response
    )
    return str(handshake_reply)


def setup_websocket(request):
    if not is_websocket(request):
        return None
    protocol_version = get_websocket_version(request)
    if protocol_version == 75:
        handshake_reply = make_version_75_handshake_replay(request)
    elif protocol_version == 76:
        handshake_reply = make_version_76_handshake_replay(request)
    else:
        handshake_reply = make_version_rfc6455_handshake_replay(request)
    if 'gunicorn.socket' in request.META:
        socket = request.META['gunicorn.socket'].dup()
    else:
        socket = getattr(
            request.META['wsgi.input'],
            '_sock',
            None,
        )
        if not socket:
            request.META['wsgi.input'].rfile._sock
        socket = socket.dup()
    return WebSocket(
        socket,
        protocol=request.META.get('HTTP_WEBSOCKET_PROTOCOL'),
        version=protocol_version,
        handshake_reply=handshake_reply,
    )


class WebSocket(object):
    """
    A websocket object that handles the details of
    serialization/deserialization to the socket.

    The primary way to interact with a :class:`WebSocket` object is to
    call :meth:`send` and :meth:`wait` in order to pass messages back
    and forth with the browser.
    """
    _socket_recv_bytes = 4096


    def __init__(self, socket, protocol, version=76,
        handshake_reply=None, handshake_sent=None):
        '''
        Arguments:

        - ``socket``: An open socket that should be used for WebSocket
          communciation.
        - ``protocol``: not used yet.
        - ``version``: The WebSocket spec version to follow (default is 76)
        - ``handshake_reply``: Handshake message that should be sent to the
          client when ``send_handshake()`` is called.
        - ``handshake_sent``: Whether the handshake is already sent or not.
          Set to ``False`` to prevent ``send_handshake()`` to do anything.
        '''
        self.socket = socket
        self.protocol = protocol
        self.version = version
        self.closed = False
        self.handshake_reply = handshake_reply
        if handshake_sent is None:
            self._handshake_sent = not bool(handshake_reply)
        else:
            self._handshake_sent = handshake_sent
        self._buffer = ""
        self._message_queue = collections.deque()

    def send_handshake(self):
        self.socket.sendall(self.handshake_reply)
        self._handshake_sent = True

    @classmethod
    def _pack_message(cls, version, message):
        """Pack the message inside ``00`` and ``FF``

        As per the dataframing section (5.3) for the websocket spec
        """
        if isinstance(message, unicode):
            message = message.encode('utf-8')
        elif not isinstance(message, str):
            message = str(message)
        if version in [76,75]:
            packed = "\x00%s\xFF" % message
        if version in [13]:
            message_length = len(message)
            if message_length <= 125:
                #Data length is one byte.
                hd = "\x81" + struct.pack('B',len(message))
            elif message_length <= 65535:
                #Data length is two byte.
                lbyte=[message_length&65280,message_length&255]
                hd = "\x81" + struct.pack('B',126)+''.join([struct.pack('B',byte) for byte in lbyte])
            else:
                #Data length is four byte.
                mask_bytes=range(1.9).reverse()
                mask_bytes.pop()
                mask_bytes.append(0)
                lbyte = [message_length&255*(16**mask_byte) for mask_byte in mask_bytes]
                hd = "\x81" + struct.pack('B',127)[0]+''.join([struct.pack('B',byte) for byte in lbyte])
            packed = hd + message
        return packed

    def _parse_message_queue_old(self):
        """ Parses for messages in the buffer *buf*.  It is assumed that
        the buffer contains the start character for a message, but that it
        may contain only part of the rest of the message.

        Returns an array of messages, and the buffer remainder that
        didn't contain any full messages."""
        msgs = []
        end_idx = 0
        buf = self._buffer
        while buf:
            frame_type = ord(buf[0])
            if frame_type == 0:
                # Normal message.
                end_idx = buf.find("\xFF")
                if end_idx == -1: #pragma NO COVER
                    break
                msgs.append(buf[1:end_idx].decode('utf-8', 'replace'))
                buf = buf[end_idx+1:]
            elif frame_type == 255:
                # Closing handshake.
                assert ord(buf[1]) == 0, "Unexpected closing handshake: %r" % buf
                self.closed = True
                break
            else:
                raise ValueError("Don't understand how to parse this type of message: %r" % buf)
        self._buffer = buf
        return msgs

    def _parse_message_queue_rfc(self):
        msgs=[]
        buf = self._buffer
        while buf:
            fin = (ord(buf[0]) & 128) == 128
            opcode = ord(buf[0]) & 15
            if opcode == 8:
                #closing handshake.
                self.socket.close()
                self.closed = True
                break
            if opcode == 9:
                #process repuest Ping
                pong_frame = '0x8A' + buf[1:len(buf)]
                self.socket.sendall(pong_frame)
                break

            mask = (ord(buf[1]) & 128) == 128
            # extract length of payload
            payload_data_length = ord(buf[1]) & 127
            offset = 2
            if payload_data_length == 126:
                hex=struct.unpack('BB',buf[2:4])
                payload_data_length=hex[0]*16**2+hex[1]
                offset += 2
            elif payload_data_length == 127:
                hex = struct.unpack('BBBBBBBB',buf[2:10])
                payload_data_length=0
                for index in range(0,8):
                    if index == 7:
                        index=0
                    payload_data_length+=hex[index]*16**(8-index)
                offset += 8
            # extract mask key
            if mask:
                mask_key = buf[offset:offset+4]
                offset += 4
            # extract data
            data = buf[offset:offset+payload_data_length]
            data_str = ''
            if mask:
                #unmask
                for index in range(0,payload_data_length):
                    one_data=struct.unpack('BB',data[index]+mask_key[index%4])
                    data_str += chr(one_data[0] ^ one_data[1])
            buf=buf[offset+payload_data_length:]
        msgs.append(data_str.decode('utf-8','replace'))
        return msgs

    def _parse_message_queue(self):
        """ Parses for messages in the buffer *buf*.  It is assumed that
        the buffer contains the start character for a message, but that it
        may contain only part of the rest of the message.

        Returns an array of messages, and the buffer remainder that
        didn't contain any full messages."""
        if self.version == 13:
            return self._parse_message_queue_rfc()
        return self._parse_message_queue_old()

    def send(self, message):
        '''
        Send a message to the client. *message* should be convertable to a
        string; unicode objects should be encodable as utf-8.
        '''
        if not self.closed:
            packed = self._pack_message(self.version, message)
            self.socket.sendall(packed)

    def _socket_recv(self):
        '''
        Gets new data from the socket and try to parse new messages.
        '''
        delta = self.socket.recv(self._socket_recv_bytes)
        if delta == '':
            return False
        self._buffer += delta
        msgs = self._parse_message_queue()
        self._message_queue.extend(msgs)
        return True

    def _socket_can_recv(self, timeout=0.0):
        '''
        Return ``True`` if new data can be read from the socket.
        '''
        r, w, e = [self.socket], [], []
        try:
            r, w, e = select.select(r, w, e, timeout)
        except select.error, err:
            if err.args[0] == EINTR:
                return False
            raise
        return self.socket in r

    def _get_new_messages(self):
        # read as long from socket as we need to get a new message.
        while self._socket_can_recv():
            self._socket_recv()
            if self._message_queue:
                return

    def count_messages(self):
        '''
        Returns the number of queued messages.
        '''
        self._get_new_messages()
        return len(self._message_queue)

    def has_messages(self):
        '''
        Returns ``True`` if new messages from the socket are available, else
        ``False``.
        '''
        if self._message_queue:
            return True
        self._get_new_messages()
        if self._message_queue:
            return True
        return False

    def read(self, fallback=None):
        '''
        Return new message or ``fallback`` if no message is available.
        '''
        if self.has_messages():
            return self._message_queue.popleft()
        return fallback

    def wait(self):
        '''
        Waits for and deserializes messages. Returns a single message; the
        oldest not yet processed.
        '''
        while not self._message_queue:
            # Websocket might be closed already.
            if self.closed:
                return None
            # no parsed messages, must mean buf needs more data
            new_data = self._socket_recv()
            if not new_data:
                return None
        return self._message_queue.popleft()

    def __iter__(self):
        '''
        Use ``WebSocket`` as iterator. Iteration only stops when the websocket
        gets closed by the client.
        '''
        while True:
            message = self.wait()
            if message is None:
                return
            yield message

    def _send_closing_frame(self, ignore_send_errors=False):
        '''
        Sends the closing frame to the client, if required.
        '''
        if self.version == 76 and not self.closed:
            try:
                self.socket.sendall("\xff\x00")
            except SocketError:
                # Sometimes, like when the remote side cuts off the connection,
                # we don't care about this.
                if not ignore_send_errors:
                    raise
            self.closed = True
        elif self.version== 13:
            pass

    def close(self):
        '''
        Forcibly close the websocket.
        '''
        self._send_closing_frame()
