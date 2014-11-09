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
from __future__ import absolute_import

import os

from flask import Flask
from gae_mini_profiler.profiler import ProfilerWSGIMiddleware
from gae_mini_profiler.templatetags import profiler_includes

from .config import get_config, set_config
from .dropbox import mod as dropbox
from .reader import mod as reader
from .util import MethodRewriteMiddleware

__all__ = 'app',


app = Flask(__name__)
app.register_blueprint(dropbox)
app.register_blueprint(reader)

app.secret_key = get_config('secret_key')
if app.secret_key is None:
    app.secret_key = os.urandom(24)
    set_config('secret_key', app.secret_key)

app.jinja_env.globals['profiler_includes'] = profiler_includes

app.wsgi_app = MethodRewriteMiddleware(app.wsgi_app)
app.wsgi_app = ProfilerWSGIMiddleware(app.wsgi_app)
