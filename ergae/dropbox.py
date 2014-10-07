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

import random

from dropbox.client import DropboxOAuth2Flow
from flask import (Blueprint, redirect, render_template, request, session,
                   url_for)

from .config import get_config, set_config


mod = Blueprint('dropbox', __name__, url_prefix='/dropbox')


def get_auth_flow():
    app_key = get_config('dropbox_app_key')
    app_secret = get_config('dropbox_app_secret')
    if app_key and app_secret:
        locale = request.accept_languages and request.accept_languages.best
        return DropboxOAuth2Flow(app_key, app_secret, url_for('.finish_auth'),
                                 session, 'dropbox-auth-csrf-token',
                                 locale)


@mod.route('/')
def start_auth():
    auth_flow = get_auth_flow()
    if not auth_flow:
        return redirect(url_for('.appkey_form'))
    return render_template('dropbox/start_auth.html')


@mod.route('/callback/')
def finish_auth():
    pass


def make_key_example():
    a_ord = ord('a')
    chars = ''.join(chr(a_ord + i) for i in xrange(25))
    chars += ''.join(str(i) for i in xrange(10))
    return ''.join(random.choice(chars) for _ in xrange(15))


@mod.route('/appkey/')
def appkey_form():
    return render_template('dropbox/appkey_form.html',
                           app_key_example=make_key_example(),
                           app_secret_example=make_key_example())


@mod.route('/appkey/', methods=['POST'])
def save_appkey():
    app_key = request.form['app_key']
    app_secret = request.form['app_secret']
    set_config('dropbox_app_key', app_key)
    set_config('dropbox_app_secret', app_secret)
    return redirect(url_for('.start_auth'))