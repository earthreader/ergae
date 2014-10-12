# ergae --- Earth Reader on Google App Engine
# Copyright (C) 2014 Hong Minhee
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
import re

__all__ = 'MethodRewriteMiddleware',


class MethodRewriteMiddleware(object):
    """The WSGI middleware that overrides HTTP methods for old browsers.
    HTML4 and XHTML only specify ``POST`` and ``GET`` as HTTP methods that
    ``<form>`` elements can use.  HTTP itself however supports a wider
    range of methods, and it makes sense to support them on the server.

    If you however want to make a form submission with ``PUT`` for instance,
    and you are using a client that does not support it, you can override it
    by using this middleware and appending ``?_method=PUT`` to the
    ``<form>`` ``action``.

    .. sourcecode:: html

       <form action="?_method=PUT" method="post">
         ...
       </form>

    :param app: WSGI application to wrap
    :type app: :class:`collections.Callable`
    :param input_name: the field name of the query to be aware of
    :type input_name: :class:`basestring`

    .. seealso::
    
       `Overriding HTTP Methods for old browsers`__ --- Flask Snippets
          A snippet written by Armin Ronacher.

    __ http://flask.pocoo.org/snippets/38/

    """

    #: (:class:`collections.Set`) The set of allowed HTTP methods.
    ALLOWED_METHODS = frozenset(['HEAD', 'GET', 'POST', 'PUT', 'DELETE'])

    #: (:class:`re.RegexObject`) The query pattern.
    PATTERN = re.compile(
        r'(?:^|&)_method=(' + '|'.join(re.escape(m) for m in ALLOWED_METHODS) +
        r')(?:&|$)'
    )

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        if (environ.get('REQUEST_METHOD', '').upper() == 'POST'):
            match = self.PATTERN.search(environ.get('QUERY_STRING', ''))
            if match:
                environ = dict(environ)
                environ['REQUEST_METHOD'] = match.group(1)
        return self.app(environ, start_response)
