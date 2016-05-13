from base64 import b64encode
from hashlib import sha1
import types

from ws4py import WS_KEY, WS_VERSION
from ws4py.messaging import Message
from ws4py.streaming import Stream


class MalformedWebSocket(ValueError):
    pass


def setup_websocket(request):
    if 'Upgrade' in request.META.get('HTTP_CONNECTION', None) and \
        request.META.get('HTTP_UPGRADE', None).lower() == 'websocket':

        version = request.META.get('HTTP_SEC_WEBSOCKET_VERSION')
        version_is_valid = False
        if version:
            try:
                version = int(version)
            except:
                pass
            else:
                version_is_valid = version in WS_VERSION

        if not version_is_valid:
            raise MalformedWebSocket

        # Compute the challenge response
        key = request.META['HTTP_SEC_WEBSOCKET_KEY']
        handshake_response = b64encode(sha1(key + WS_KEY).digest())

        # TODO : protocol negociation? Could be specified in the decorator...
        protocols = request.META.get('HTTP_SEC_WEBSOCKET_PROTOCOL')

        # TODO : the 'Origin' field should be validated by application code
        # (or configuration/per-view option)

        handshake_reply = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n")
        handshake_reply += "Sec-WebSocket-Version: %s\r\n" % version
        if protocols:
            handshake_reply += "Sec-WebSocket-Protocol: %s\r\n" % protocols
        handshake_reply += "Sec-WebSocket-Accept: %s\r\n" % handshake_response
        handshake_reply += "\r\n"

        # Here we want to make sure that Django doesn't handle this request
        # anymore
        #request.META['wsgi.input']._sock = None
        socket = request.META['wsgi.input']._sock.dup()
        # dup() is not portable because the folks writing Python forgot to
        # backport it from 3.x to 2.7

        return WebSocket(
            socket,
            handshake_reply,
            protocols)
    return None


DEFAULT_READING_SIZE = 2

# This class was adapted from ws4py.websocket:WebSocket
# Changes include:
#  * process() inlined into _run, uses yield instead of received_message(),
#     making it a generator
#  * other callbacks removed
#  * process() inlined into _run
#  * added __iter__()
#  * send_handshake() method
class WebSocket(object):
    def __init__(self, sock, handshake_reply, protocols=None):
        self.stream = Stream(always_mask=False)
        self.handshake_reply = handshake_reply
        self.handshake_sent = False
        self.protocols = protocols
        self.sock = sock
        self.client_terminated = False
        self.server_terminated = False
        self.reading_buffer_size = DEFAULT_READING_SIZE
        self.sender = self.sock.sendall

        # This was initially a loop that used callbacks in ws4py
        # Here it was turned into a generator, the callback replaced by yield
        self.runner = self._run()

    def send_handshake(self):
        self.sender(self.handshake_reply)
        self.handshake_sent = True

    def wait(self):
        """
        Reads a message from the websocket, blocking and responding to wire
        messages until one becomes available.
        """
        try:
            return self.runner.next()
        except StopIteration:
            return None

    def send(self, payload, binary=False):
        """
        Sends the given ``payload`` out.

        If ``payload`` is some bytes or a bytearray,
        then it is sent as a single message not fragmented.

        If ``payload`` is a generator, each chunk is sent as part of
        fragmented message.

        If ``binary`` is set, handles the payload as a binary message.
        """
        message_sender = self.stream.binary_message if binary else self.stream.text_message

        if isinstance(payload, basestring) or isinstance(payload, bytearray):
            self.sender(message_sender(payload).single(mask=self.stream.always_mask))

        elif isinstance(payload, Message):
            self.sender(payload.single(mask=self.stream.always_mask))

        elif type(payload) == types.GeneratorType:
            bytes = payload.next()
            first = True
            for chunk in payload:
                self.sender(message_sender(bytes).fragment(first=first, mask=self.stream.always_mask))
                bytes = chunk
                first = False

            self.sender(message_sender(bytes).fragment(last=True, mask=self.stream.always_mask))

        else:
            raise ValueError("Unsupported type '%s' passed to send()" % type(payload))

    def _cleanup(self):
        """
        Frees up resources used by the endpoint.
        """
        self.sender = None
        self.sock = None
        self.stream._cleanup()
        self.stream = None

    def _run(self):
        """
        Performs the operation of reading from the underlying
        connection in order to feed the stream of bytes.

        We start with a small size of two bytes to be read
        from the connection so that we can quickly parse an
        incoming frame header. Then the stream indicates
        whatever size must be read from the connection since
        it knows the frame payload length.

        Note that we perform some automatic operations:

        * On a closing message, we respond with a closing
          message and finally close the connection
        * We respond to pings with pong messages.
        * Whenever an error is raised by the stream parsing,
          we initiate the closing of the connection with the
          appropiate error code.
        """
        self.sock.setblocking(True)
        s = self.stream
        try:
            sock = self.sock

            while not self.terminated:
                bytes = sock.recv(self.reading_buffer_size)
                if not bytes and self.reading_buffer_size > 0:
                    break

                self.reading_buffer_size = s.parser.send(bytes) or DEFAULT_READING_SIZE

                if s.closing is not None:
                    if not self.server_terminated:
                        self.close(s.closing.code, s.closing.reason)
                    else:
                        self.client_terminated = True
                    break

                if s.errors:
                    for error in s.errors:
                        self.close(error.code, error.reason)
                    s.errors = []
                    break

                if s.has_message:
                    yield s.message
                    s.message.data = None
                    s.message = None
                else:
                    if s.pings:
                        for ping in s.pings:
                            self.sender(s.pong(ping.data))
                        s.pings = []

                    if s.pongs:
                        s.pongs = []
        finally:
            self.client_terminated = self.server_terminated = True

            s = sock = None
            self.close_connection()
            self._cleanup()

    def close(self, code=1000, reason=''):
        """
        Call this method to initiate the websocket connection
        closing by sending a close frame to the connected peer.
        The ``code`` is the status code representing the
        termination's reason.

        Once this method is called, the ``server_terminated``
        attribute is set. Calling this method several times is
        safe as the closing frame will be sent only the first
        time.

        .. seealso:: Defined Status Codes http://tools.ietf.org/html/rfc6455#section-7.4.1
        """
        if not self.server_terminated:
            self.server_terminated = True
            self.sender(self.stream.close(code=code, reason=reason).single(mask=self.stream.always_mask))

    def close_connection(self):
        """
        Shutdowns then closes the underlying connection.
        """
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        except:
            pass

    @property
    def terminated(self):
        """
        Returns ``True`` if both the client and server have been
        marked as terminated.
        """
        return self.client_terminated is True and self.server_terminated is True

    def __iter__(self):
        return self.runner
