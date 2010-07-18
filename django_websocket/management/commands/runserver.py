'''
Monkey patching django's builtin ``runserver`` command to support
multithreaded concurrent requests. This is necessary to have more than one
WebSocket open at a time.

The implementation monkey patches the code instead of subclassing the original
WSGIServer since there is no easy way to inject the new, inherited class into
the runserver command.
'''
from django.core.management.commands.runserver import Command as _Runserver
from django.core.servers.basehttp import WSGIServer
from SocketServer import ThreadingMixIn
from optparse import make_option


class Command(_Runserver):
    option_list = _Runserver.option_list + (
        make_option('--multithreaded', action='store_true', dest='multithreaded', default=False,
            help='Run development server with support for concurrent requests.'),
    )

    def handle(self, *args, **options):
        multithreaded = options.pop('multithreaded')
        if multithreaded:
            # monkey patch WSGIServer to support concurrent requests
            skip_attrs = ('__doc__', '__module__')
            patch_attrs = dir(ThreadingMixIn)
            patch_attrs = [a for a in patch_attrs if a not in skip_attrs]
            for attr in patch_attrs:
                setattr(WSGIServer, attr, getattr(ThreadingMixIn, attr))
            # persuade python to use mixin methods
            WSGIServer.__bases__ = WSGIServer.__bases__ + (ThreadingMixIn,)
        super(Command, self).handle(*args, **options)
