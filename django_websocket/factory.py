import logging
import socket
import collections
from .protocols import get_websocket_protocol


logger = logging.getLogger(__name__)


class WebSocketFactory(object):

    def __init__(self, request):
        self.request = request

    def is_websocket(self):
        """check the websocket"""
        if self.request.META.get(
            'HTTP_UPGRADE', ""
        ).lower() == 'websocket':
            return True
        else:
            return False

    def get_websocket_version(self):
        if 'HTTP_SEC_WEBSOCKET_KEY1' in self.request.META:
            protocol_version = '76'
            if 'HTTP_SEC_WEBSOCKET_KEY2' not in self.request.META:
                raise ValueError('HTTP_SEC_WEBSOCKET_KEY2 NOT FOUND')
        elif 'HTTP_SEC_WEBSOCKET_KEY' in self.request.META:
            protocol_version = '13'
        else:
            protocol_version = '75'
        return protocol_version

    def get_wsgi_sock(self):
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
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  
        return sock

    def create_websocket(self):
        if not self.is_websocket():
            return None
        try:
            protocol = get_websocket_protocol(self.get_websocket_version())(
                sock = self.get_wsgi_sock(),
                headers = self.request.META
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

    def accept_connection(self):
        self.protocol.accept_connection()

    def send(self, message):
        '''
        Send a message to the client. *message* should be convertable to a
        string; unicode objects should be encodable as utf-8.
        '''
        if not self.closed:
            self.protocol.write(message)

    def _get_new_messages(self):
        # read as long from socket as we need to get a new message.
        while self.protocol.can_read():
            self._message_queue.append(self.protocol.read())
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
            new_data = self.protocol.read()
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
        if not self.closed:
            self.protocol.close()
            self.closed = True
    
    def abort(self):
        if not self.closed:
            self.protocol.abort()
            self.closed = True
