from django.conf import settings
from django.http import HttpResponseBadRequest
from django_websocket.websocket import setup_websocket, MalformedWebSocket


WEBSOCKET_ACCEPT_ALL = getattr(settings, 'WEBSOCKET_ACCEPT_ALL', False)


class WebSocketMiddleware(object):
    def process_request(self, request):
        try:
            request.websocket = setup_websocket(request)
        except MalformedWebSocket, e:
            request.websocket = None
            request.is_websocket = lambda: False
            return HttpResponseBadRequest()
        if request.websocket is None:
            request.is_websocket = lambda: False
        else:
            request.is_websocket = lambda: True

    def process_view(self, request, view_func, view_args, view_kwargs):
        # open websocket if its an accepted request
        if request.is_websocket():
            # deny websocket request if view can't handle websocket
            if not WEBSOCKET_ACCEPT_ALL and \
                not getattr(view_func, 'accept_websocket', False):
                return HttpResponseBadRequest()
            # everything is fine .. so prepare connection by sending handshake
            request.websocket.send_handshake()
        elif getattr(view_func, 'require_websocket', False):
            # websocket was required but not provided
            return HttpResponseBadRequest()

    def process_response(self, request, response):
        if request.is_websocket() and request.websocket.handshake_sent:
            request.websocket.close()
        return response
