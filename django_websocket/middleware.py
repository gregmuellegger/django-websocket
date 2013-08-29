import logging
from django.conf import settings
from django.http import HttpResponseBadRequest
from .factory import WebSocketFactory


WEBSOCKET_ACCEPT_ALL = getattr(settings, 'WEBSOCKET_ACCEPT_ALL', False)
logger = logging.getLogger(__name__)


class WebSocketMiddleware(object):
    @classmethod
    def process_request(cls, request):
        try:
            factory = WebSocketFactory(request)
            request.websocket = factory.create_websocket()
        except ValueError as e:
            logger.debug(e)
            request.websocket = None
            request.is_websocket = lambda: False
            return HttpResponseBadRequest()
        if request.websocket is None:
            request.is_websocket = lambda: False
        else:
            request.is_websocket = lambda: True

    @classmethod
    def process_view(cls, request, view_func, view_args, view_kwargs):
        # open websocket if its an accepted request
        if request.is_websocket():
            # deny websocket request if view can't handle websocket
            if not WEBSOCKET_ACCEPT_ALL and \
                not getattr(view_func, 'accept_websocket', False):
                return HttpResponseBadRequest()
            # everything is fine .. so prepare connection by sending handshake
            request.websocket.accept_connection()
        elif getattr(view_func, 'require_websocket', False):
            # websocket was required but not provided
            return HttpResponseBadRequest()

    @classmethod
    def process_response(cls, request, response):
        if request.is_websocket():
            request.websocket.close()
        return response

    @classmethod
    def process_exception(cls, request, exception):
        if request.is_websocket():
            request.websocket.close()
