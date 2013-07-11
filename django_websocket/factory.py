import collections
import base64
import select
import string
import struct
from hashlib import md5, sha1
from errno import EINTR
from socket import error as SocketError
from .protocols import WebSocketProtocol


class WebSocketFactory(object):

    mapping = {
        13: WebSocketProtocol
    }

    def __init__(self, request):
        self.request = request

    def is_websocket(self):
        """check the websocket"""
        if self.request.META.get(
            'HTTP_CONNECTION', ""
        ).lower() == 'upgrade' and self.request.META.get(
            'HTTP_UPGRADE', ""
        ).lower() == 'websocket':
            return True
        else:
            return False

    def version(self):
        if 'HTTP_SEC_WEBSOCKET_KEY1' in self.request.META:
            protocol_version = 76
            if 'HTTP_SEC_WEBSOCKET_KEY2' not in self.request.META:
                raise ValueError('HTTP_SEC_WEBSOCKET_KEY2 NOT FOUND')
        elif 'HTTP_SEC_WEBSOCKET_KEY' in self.request.META:
            protocol_version = 13
        else:
            protocol_version = 75
        return protocol_version

    def create_handshake_replay(self):
        key = self.request.META['HTTP_SEC_WEBSOCKET_KEY']
        #Create hand shake response for that is after version 07
        handshake_response = base64.b64encode(
            sha1(
                key.encode(
                    "utf-8"
                )+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode("utf-8")
            ).digest()
        )
        handshake_reply = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % handshake_response
        )
        return str(handshake_reply)

    def get_request_sock(self):
        try:
            if 'gunicorn.socket' in self.request.META:
                sock = self.request.META['gunicorn.socket'].dup()
            else:
                sock = getattr(
                    self.request.META['wsgi.input'],
                    '_sock',
                    None,
                )
                if not sock:
                    sock = self.request.META['wsgi.input'].rfile._sock
            sock = sock.dup()
            return sock
        except AttributeError as e:
            logger.exception(e)
            return None

    def create_websocket(self):
        if not self.is_websocket():
            return None
        sock = self.get_request_sock()
        if sock:
            try:
                protocol = self.mapping[self.version()](
                    sock,
                    self.create_handshake_replay()
                )
                return WebSocket(protocol=protocol)
            except KeyError as e:
                logger.exception(e)
        return None


class WebSocket(object):
    """
    A websocket object that handles the details of
    serialization/deserialization to the socket.

    The primary way to interact with a :class:`WebSocket` object is to
    call :meth:`send` and :meth:`wait` in order to pass messages back
    and forth with the browser.
    """

    def __init__(self, protocol):
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
        self.protocol = protocol
        self.closed = False
        self._message_queue = collections.deque()

    def send_handshake(self):
        self.protocol.send_handshake_replay()

    def send(self, message):
        '''
        Send a message to the client. *message* should be convertable to a
        string; unicode objects should be encodable as utf-8.
        '''
        if not self.closed:
            self.protocol.send(message)

    def _get_new_messages(self):
        # read as long from socket as we need to get a new message.
        while self.protocol.can_recv():
            self._message_queue.append(self.protocol.recv())
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
            new_data = self.protocol.recv()
            if not new_data:
                return None
            self._message_queue.append(new_data)
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

    def close(self):
        '''
        Forcibly close the websocket.
        '''
        self.closed = True
        self.protocol.close()
