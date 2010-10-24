from django.test import Client
from django.core.handlers.wsgi import WSGIRequest


class RequestFactory(Client):
    """
    Class that lets you create mock Request objects for use in testing.

    Usage:

    rf = RequestFactory()
    get_request = rf.get('/hello/')
    post_request = rf.post('/submit/', {'foo': 'bar'})

    This class re-uses the django.test.client.Client interface, docs here:
    http://www.djangoproject.com/documentation/testing/#the-test-client

    Once you have a request object you can pass it to any view function,
    just as if that view had been hooked up using a URLconf.

    """
    def request(self, **request):
        """
        Similar to parent class, but returns the request object as soon as it
        has created it.
        """
        environ = {
            'HTTP_COOKIE': self.cookies,
            'PATH_INFO': '/',
            'QUERY_STRING': '',
            'REQUEST_METHOD': 'GET',
            'SCRIPT_NAME': '',
            'SERVER_NAME': 'testserver',
            'SERVER_PORT': 80,
            'SERVER_PROTOCOL': 'HTTP/1.1',
        }
        environ.update(self.defaults)
        environ.update(request)
        return WSGIRequest(environ)


class WebsocketFactory(RequestFactory):
    def __init__(self, *args, **kwargs):
        self.protocol_version = kwargs.pop('websocket_version', 75)
        super(WebsocketFactory, self).__init__(*args, **kwargs)

    def request(self, **request):
        """
        Returns a request simliar to one from a browser which wants to upgrade
        to a websocket connection.
        """
        environ = {
            'HTTP_COOKIE': self.cookies,
            'PATH_INFO': '/',
            'QUERY_STRING': '',
            'REQUEST_METHOD': 'GET',
            'SCRIPT_NAME': '',
            'SERVER_NAME': 'testserver',
            'SERVER_PORT': 80,
            'SERVER_PROTOCOL': 'HTTP/1.1',
            # WebSocket specific headers
            'HTTP_CONNECTION': 'Upgrade',
            'HTTP_UPGRADE': 'WebSocket',
        }
        if self.protocol_version == 76:
            raise NotImplementedError(u'This version is not yet supported.')
        environ.update(self.defaults)
        environ.update(request)
        return WSGIRequest(environ)
