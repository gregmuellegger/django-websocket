#This file mainly exists to allow python setup.py test to work.
import os, sys
os.environ['DJANGO_SETTINGS_MODULE'] = 'django_websocket_tests.settings'
test_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, test_dir)

import django
from django.test.utils import get_runner
from django.conf import settings

def runtests():
    TestRunner = get_runner(settings)
    if django.VERSION[:2] > (1,1):
        test_runner = TestRunner(verbosity=1, interactive=True)
        failures = test_runner.run_tests(settings.TEST_APPS)
    else:
        # test runner is not class based, this means we use django 1.1.x or
        # earlier.
        failures = TestRunner(settings.TEST_APPS, verbosity=1, interactive=True)
    sys.exit(bool(failures))

if __name__ == '__main__':
    runtests()
