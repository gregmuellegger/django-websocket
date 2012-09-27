Changelog
=========

Release 0.4.0
-------------

- Removed multithreaded development server. Django 1.4 uses multithreading by
  default in the ``runserver`` command.

Release 0.3.0
-------------

- Added multithreaded development server.

Release 0.2.0
-------------

- Changed name of attribute ``WebSocket.websocket_closed`` to
  ``WebSocket.closed``.
- Changed behaviour of ``WebSocket.close()`` method. Doesn't close system
  socket - it's still needed by django!
- You can run tests now with ``python setup.py test``.
- Refactoring ``WebSocket`` class.
- Adding ``WebSocket.read()`` which returns ``None`` if no new messages are
  available instead of blocking like ``WebSocket.wait()``.
- Adding example project to play around with.
- Adding ``WebSocket.has_messages()``. You can use it to check if new messages
  are ready to be processed.
- Adding ``WebSocket.count_messages()``.
- Removing ``BaseWebSocketMiddleware`` - is replaced by
  ``WebSocketMiddleware``. Don't need for a base middleware anymore. We can
  integrate everything in one now.

Release 0.1.1
-------------

- Fixed a bug in ``BaseWebSocketMiddleware`` that caused an exception in
  ``process_response`` if ``setup_websocket`` failed. Thanks to cedric salaun
  for the report.

Release 0.1.0
-------------

- Initial release
