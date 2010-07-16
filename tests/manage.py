#!/usr/bin/env python
import os
import sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

try:
    import django_websocket
except ImportError:
    sys.path.insert(0, os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    try:
        import django_websocket
    except ImportError:
        print "Cannot find a distribution of django_websocket."
        sys.exit(1)

from django.core import management

if __name__ == "__main__":
    management.execute_from_command_line()
