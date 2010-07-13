import collections
import string
import struct
try:
    from hashlib import md5
except ImportError: #pragma NO COVER
    from md5 import md5
from socket import error as SocketError


class MalformedWebSocket(ValueError):
    pass


def _extract_number(value):
    """
    Utility function which, given a string like 'g98sd  5[]221@1', will
    return 9852211. Used to parse the Sec-WebSocket-Key headers.
    """
    out = ""
    spaces = 0
    for char in value:
        if char in string.digits:
            out += char
        elif char == " ":
            spaces += 1
    return int(out) / spaces


def setup_websocket(request):
    if request.META.get('HTTP_CONNECTION', None) == 'Upgrade' and \
        request.META.get('HTTP_UPGRADE', None) == 'WebSocket':

        # See if they sent the new-format headers
        if 'HTTP_SEC_WEBSOCKET_KEY1' in request.META:
            protocol_version = 76
            if 'HTTP_SEC_WEBSOCKET_KEY2' not in request.META:
                raise MalformedWebSocket()
        else:
            protocol_version = 75

        # If it's new-version, we need to work out our challenge response
        if protocol_version == 76:
            key1 = _extract_number(request.META['HTTP_SEC_WEBSOCKET_KEY1'])
            key2 = _extract_number(request.META['HTTP_SEC_WEBSOCKET_KEY2'])
            # There's no content-length header in the request, but it has 8
            # bytes of data.
            key3 = request.META['wsgi.input'].read(8)
            key = struct.pack(">II", key1, key2) + key3
            handshake_response = md5(key).digest()

        location = 'ws://%s%s' % (request.get_host(), request.path)
        qs = request.META.get('QUERY_STRING')
        if qs:
            location += '?' + qs
        if protocol_version == 75:
            handshake_reply = (
                "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
                "Upgrade: WebSocket\r\n"
                "Connection: Upgrade\r\n"
                "WebSocket-Origin: %s\r\n"
                "WebSocket-Location: %s\r\n\r\n" % (
                    request.META.get('HTTP_ORIGIN'),
                    location))
        elif protocol_version == 76:
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

        else:
            raise MalformedWebSocket("Unknown WebSocket protocol version.")
        socket = request.META['wsgi.input']._sock.dup()
        return WebSocket(
            socket,
            protocol=request.META.get('HTTP_WEBSOCKET_PROTOCOL'),
            version=protocol_version,
            handshake_reply=handshake_reply,
        )
    return None


class WebSocket(object):
    """A websocket object that handles the details of
    serialization/deserialization to the socket.

    The primary way to interact with a :class:`WebSocket` object is to
    call :meth:`send` and :meth:`wait` in order to pass messages back
    and forth with the browser.
    """
    def __init__(self, socket, protocol, version=76,
        handshake_reply=None, handshake_sent=None):
        """
        Arguments:

        - ``version``: The WebSocket spec version to follow (default is 76)
        """
        self.socket = socket
        self.protocol = protocol
        self.version = version
        self.websocket_closed = False
        self.handshake_reply = handshake_reply
        if handshake_sent is None:
            self._handshake_sent = not bool(handshake_reply)
        else:
            self._handshake_sent = handshake_sent
        self._buf = ""
        self._msgs = collections.deque()

    def send_handshake(self):
        self.socket.sendall(self.handshake_reply)
        self._handshake_sent = True

    @staticmethod
    def _pack_message(message):
        """Pack the message inside ``00`` and ``FF``

        As per the dataframing section (5.3) for the websocket spec
        """
        if isinstance(message, unicode):
            message = message.encode('utf-8')
        elif not isinstance(message, str):
            message = str(message)
        packed = "\x00%s\xFF" % message
        return packed

    def _parse_messages(self):
        """ Parses for messages in the buffer *buf*.  It is assumed that
        the buffer contains the start character for a message, but that it
        may contain only part of the rest of the message.

        Returns an array of messages, and the buffer remainder that
        didn't contain any full messages."""
        msgs = []
        end_idx = 0
        buf = self._buf
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
                self.websocket_closed = True
                break
            else:
                raise ValueError("Don't understand how to parse this type of message: %r" % buf)
        self._buf = buf
        return msgs

    def send(self, message):
        """Send a message to the browser.  *message* should be
        convertable to a string; unicode objects should be encodable
        as utf-8."""
        packed = self._pack_message(message)
        self.socket.sendall(packed)

    def wait(self):
        """Waits for and deserializes messages. Returns a single
        message; the oldest not yet processed."""
        while not self._msgs:
            # Websocket might be closed already.
            if self.websocket_closed:
                return None
            # no parsed messages, must mean buf needs more data
            delta = self.socket.recv(8096)
            if delta == '':
                return None
            self._buf += delta
            msgs = self._parse_messages()
            self._msgs.extend(msgs)
        return self._msgs.popleft()

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
        """Sends the closing frame to the client, if required."""
        if self.version == 76 and not self.websocket_closed:
            try:
                self.socket.sendall("\xff\x00")
            except SocketError:
                # Sometimes, like when the remote side cuts off the connection,
                # we don't care about this.
                if not ignore_send_errors:
                    raise
            self.websocket_closed = True

    def close(self):
        """Forcibly close the websocket; generally it is preferable to
        return from the handler method."""
        self._send_closing_frame()
        self.socket.shutdown(True)
        self.socket.close()

