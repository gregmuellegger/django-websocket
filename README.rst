================
django-websocket
================

**IMPORTANT: Please read the disclaimer a few sections below before you start
using django-websocket.**

The **django-websocket** module provides an implementation of the WebSocket
Protocol for django. It handles all the low-level details like establishing
the connection through sending handshake reply, parsing messages from the
browser etc...

It integrates well into django since it provides easy hooks to receive
WebSocket requests either for single views through decorators or for the whole
site through a custom middleware.

Usage
=====

You can use the ``accept_websocket`` decorator if you want to handle websocket
connections just for a single view - it will route standard HTTP requests to
the view as well. Use ``require_websocket`` to only allow WebSocket
connections but reject normal HTTP requests.

You can use a middleware if you want to have WebSockets available for *all*
URLs in your application. Add
``django_websocket.middleware.WebSocketMiddleware`` to your
``MIDDLEWARE_CLASSES`` setting. This will still reject websockets for normal
views. You have to set the ``accept_websocket`` attribute on a view to allow
websockets.

To allow websockets for *every single view*, set the ``WEBSOCKET_ACCEPT_ALL``
setting to ``True``.

The request objects passed to a view, decorated with ``accept_websocket`` or
``require_websocket`` will have the following attributes/methods attached.
These attributes are always available if you use the middleware.

``request.is_websocket()``
--------------------------

Returns either ``True`` if the request has a valid websocket or ``False`` if
its a normal HTTP request. Use this method in views that can accept both types
of requests to distinguish between them.

``request.websocket``
---------------------

After a websocket is established, the request will have a ``websocket``
attribute which provides a simple API to communicate with the client. This
attribute will be ``None`` if ``request.is_websocket()`` returns ``False``.

It has the following public methods:

``WebSocket.wait()``
~~~~~~~~~~~~~~~~~~~~

This will return exactly one message sent by the client. It will not return
before a message is received or the conection is closed by the client. In this
case the method will return ``None``.

``WebSocket.read()``
~~~~~~~~~~~~~~~~~~~~

The ``read`` method will return either a new message if available or ``None``
if no new message was received from the client. It is a non-blocking
alternative to the ``wait()`` method.

``WebSocket.count_messages()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns the number of queued messages.

``WebSocket.has_messages()``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns ``True`` if new messages are available, else ``False``.

``WebSocket.send(message)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

This will send a single message to the client.

``WebSocket.__iter__()``
~~~~~~~~~~~~~~~~~~~~~~~~

You can use the websocket as iterator. It will yield every new message sent by
the client and stop iteration after the client has closed the connection.

Error handling
--------------

The library will return a Http 400 error (Bad Request) if the client requests
a WebSocket connection, but the request is malformed or not supported by
*django-websocket*.

Examples
========

Receive one message from the client, send that message back to the client and
close the connection (by returning from the view)::

    from django_websocket import require_websocket

    @require_websocket
    def echo_once(request):
        message = request.websocket.wait()
        request.websocket.send(message)

Send websocket messages from the client as lowercase and provide same
functionallity for normal GET requests::

    from django.http import HttpResponse
    from django_websocket import accept_websocket

    def modify_message(message):
        return message.lower()

    @accept_websocket
    def lower_case(request):
        if not request.is_websocket():
            message = request.GET['message']
            message = modify_message(message)
            return HttpResponse(message)
        else:
            for message in request.websocket:
                message = modify_message(message)
                request.websocket.send(message)

Disclaimer (what you should know when using django-websocket)
=============================================================

**BIG FAT DISCLAIMER** - right at the moment its technically *NOT* possible in
any way to use a websocket with WSGI. This is a known issue but cannot be
worked around in a clean way due to some design decision that were made while
the WSGI stadard was written. At this time things like Websockets etc. didn't
exist and were not predictable.

However there are thoughts to extend the WSGI standard to make Websockets
possible. `Read here for a discussion on the Paste Users mailing list
<http://groups.google.com/group/paste-users/browse_thread/thread/2f3a5ba33b857c6c>`_.

But not only WSGI is the limiting factor. Django itself was designed around a
simple request to response scenario without Websockets in mind. This also
means that providing a standard conform websocket implemention is not possible
right now for django. However it works somehow in a not-so pretty way. So be
aware that tcp sockets might get tortured while using django-websocket.

Using in development
--------------------

Django doesn't support a multithreaded development server yet. It is still not
possible to open two concurrent requests. This makes working with WebSockets a
bit tedious - since WebSockets will require an open request by their nature.

This has the implication that you won't be able to have more than one
WebSocket open at a time when using django's ``runserver`` command. It's also
not possible to fire an AJAX request while a WebSocket is in use etc.

**django-websocket** ships with a custom ``runserver`` command that works
around these limitations. Add ``django_websocket`` to your ``INSTALLED_APPS``
settings to install it. Use your development server like you did before and
provide the ``--multithreaded`` option to enable multithreaded behaviour::

    python manage.py runserver --multithreaded

Using in production
-------------------

Be aware that **django-websocket** is just a toy for its author to play around
with at the moment. It is not recommended to use in production without knowing
what you do. There are no real tests made in the wild yet.

But this doesn't mean that the project won't grow up in the future. There will
be fixes to reported bugs and feature request are welcome to improve the API.

Please write me an email or contact me somewhere else if you have experience
with **django-websocket** in a real project or even in a production
environment.

Contribute
==========

Every contribution in any form is welcome. Ask questions, report bugs, request
new features, make rants or tell me any other critique you may have.

One of the biggest contributions you can make is giving me a quick *Thank you*
if you like this library or if it has saved you a bunch of time.

But if you want to get your hands dirty:

- Get the code from github: http://github.com/gregor-muellegger/django-websocket
- Run tests with ``python setup.py test``.
- Start coding :)
- Send me a pull request or an email with a patch.

Authors
=======

- Gregor Müllegger <gregor@muellegger.de> (http://gremu.net/)

Credits
-------

Some low-level code for WebSocket implementation is borrowed from the `eventlet
library`_.

.. _`eventlet library`: http://eventlet.net/

