#!/usr/bin/env python
# -*- coding: utf-8 -*-
from setuptools import setup


class UltraMagicString(object):
    '''
    Taken from
    http://stackoverflow.com/questions/1162338/whats-the-right-way-to-use-unicode-metadata-in-setup-py
    '''
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

    def __unicode__(self):
        return self.value.decode('UTF-8')

    def __add__(self, other):
        return UltraMagicString(self.value + str(other))

    def split(self, *args, **kw):
        return self.value.split(*args, **kw)


long_description = UltraMagicString('\n\n'.join((
    file('README').read(),
    file('CHANGES').read(),
)))


setup(
    name = u'django-websocket',
    version = u'0.3.0',
    url = u'http://pypi.python.org/pypi/django-websocket',
    license = u'BSD',
    description = u'Websocket support for django.',
    long_description = long_description,
    author = UltraMagicString('Gregor Müllegger'),
    author_email = u'gregor@muellegger.de',
    packages = [
        'django_websocket',
        'django_websocket.management',
        'django_websocket.management.commands'],
    classifiers = [
        'Development Status :: 3 - Alpha',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Utilities'
    ],
    zip_safe = True,
    install_requires = ['setuptools'],

    test_suite = 'django_websocket_tests.runtests.runtests',
    tests_require=[
        'django-test-utils',
        'mock',
    ],
)
