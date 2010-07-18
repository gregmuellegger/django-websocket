# -*- coding: utf-8 -*-
from mock import Mock
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import TestCase
from test_utils.mocks import RequestFactory
from django_websocket.decorators import accept_websocket, require_websocket
from django_websocket.websocket import WebSocket


class WebSocketTests(TestCase):
    def setUp(self):
        self.socket = Mock()
        self.protocol = '1'

    def test_send_handshake(self):
        handshake = 'Hi!'
        ws = WebSocket(self.socket, self.protocol, handshake_reply=handshake)
        self.assertEquals(ws._handshake_sent, False)
        ws.send_handshake()
        self.assertEquals(self.socket.sendall.call_count, 1)
        self.assertEquals(self.socket.sendall.call_args, ((handshake,), {}))

    def test_message_sending(self):
        ws = WebSocket(self.socket, self.protocol)
        ws.send('foobar')
        self.assertEquals(self.socket.sendall.call_count, 1)
        self.assertEquals(self.socket.sendall.call_args, (('\x00foobar\xFF',), {}))
        message = self.socket.sendall.call_args[0][0]
        self.assertEquals(type(message), str)

        ws.send(u'Küss die Hand schöne Frau')
        self.assertEquals(self.socket.sendall.call_count, 2)
        self.assertEquals(self.socket.sendall.call_args, (('\x00K\xc3\xbcss die Hand sch\xc3\xb6ne Frau\xFF',), {}))
        message = self.socket.sendall.call_args[0][0]
        self.assertEquals(type(message), str)

    def test_message_receiving(self):
        ws = WebSocket(self.socket, self.protocol)
        self.assertFalse(ws.closed)

        results = [
            '\x00spam & eggs\xFF',
            '\x00K\xc3\xbcss die Hand sch\xc3\xb6ne Frau\xFF',
            '\xFF\x00'][::-1]
        def return_results(*args, **kwargs):
            return results.pop()
        self.socket.recv.side_effect = return_results
        self.assertEquals(ws.wait(), u'spam & eggs')
        self.assertEquals(ws.wait(), u'Küss die Hand schöne Frau')

    def test_closing_socket_by_client(self):
        self.socket.recv.return_value = '\xFF\x00'

        ws = WebSocket(self.socket, self.protocol)
        self.assertFalse(ws.closed)
        self.assertEquals(ws.wait(), None)
        self.assertTrue(ws.closed)

        self.assertEquals(self.socket.shutdown.call_count, 0)
        self.assertEquals(self.socket.close.call_count, 0)

    def test_closing_socket_by_server(self):
        ws = WebSocket(self.socket, self.protocol)
        self.assertFalse(ws.closed)
        ws.close()
        self.assertEquals(self.socket.sendall.call_count, 1)
        self.assertEquals(self.socket.sendall.call_args, (('\xFF\x00',), {}))
        # don't close system socket! django still needs it.
        self.assertEquals(self.socket.shutdown.call_count, 0)
        self.assertEquals(self.socket.close.call_count, 0)
        self.assertTrue(ws.closed)

        # closing again will not send another close message
        ws.close()
        self.assertTrue(ws.closed)
        self.assertEquals(self.socket.sendall.call_count, 1)
        self.assertEquals(self.socket.shutdown.call_count, 0)
        self.assertEquals(self.socket.close.call_count, 0)

    def test_iterator_behaviour(self):
        results = [
            '\x00spam & eggs\xFF',
            '\x00K\xc3\xbcss die Hand sch\xc3\xb6ne Frau\xFF',
            '\xFF\x00'][::-1]
        expected_results = [
            u'spam & eggs',
            u'Küss die Hand schöne Frau']
        def return_results(*args, **kwargs):
            return results.pop()
        self.socket.recv.side_effect = return_results

        ws = WebSocket(self.socket, self.protocol)
        for i, message in enumerate(ws):
            self.assertEquals(message, expected_results[i])


@accept_websocket
def add_one(request):
    if request.is_websocket():
        for message in request.websocket:
            request.websocket.send(int(message) + 1)
    else:
        value = int(request.GET['value'])
        value += 1
        return HttpResponse(unicode(value))

@require_websocket
def echo_once(request):
    request.websocket.send(request.websocket.wait())


class DecoratorTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_require_websocket_decorator(self):
        # view requires websocket -> bad request
        request = self.rf.get('/echo/')
        response = echo_once(request)
        self.assertEquals(response.status_code, 400)

    def test_accept_websocket_decorator(self):
        request = self.rf.get('/add/', {'value': '23'})
        response = add_one(request)
        self.assertEquals(response.status_code, 200)
        self.assertEquals(response.content, '24')

# TODO: test views with actual websocket connection - not really possible yet
# with django's test client/request factory. Heavy use of mock objects
# necessary.
