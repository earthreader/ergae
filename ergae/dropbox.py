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

import fractions
import hashlib
import hmac
import logging
import random
import re

from dropbox.client import DropboxClient, DropboxOAuth2Flow
from dropbox.rest import ErrorResponse
from flask import (Blueprint, abort, redirect, render_template, request,
                   session, url_for)
from google.appengine.ext.deferred import defer
from werkzeug.exceptions import BadRequest, Forbidden, HTTPException

from .config import get_config, set_config
from .rest import RestClient


mod = Blueprint('dropbox', __name__, url_prefix='/dropbox')


def get_auth_flow(redirect_on_fail=True):
    app_key = get_config('dropbox_app_key')
    app_secret = get_config('dropbox_app_secret')
    if app_key and app_secret:
        locale = request.accept_languages and request.accept_languages.best
        return DropboxOAuth2Flow(app_key, app_secret,
                                 url_for('.finish_auth', _external=True),
                                 session, 'dropbox-auth-csrf-token', locale,
                                 rest_client=RestClient)
    if redirect_on_fail:
        raise Redirect(url_for('.appkey_form'))


def get_client(redirect_on_fail=True):
    access_token = get_config('dropbox_access_token')
    if access_token:
        client = DropboxClient(access_token, rest_client=RestClient)
        client.session.rest_client = RestClient
        return client
    if redirect_on_fail:
        raise Redirect(url_for('.start_auth'))


class Redirect(HTTPException):

    def __init__(self, url, code=302, description=None, response=None):
        super(Redirect, self).__init__(description, response)
        self.url = url
        self.code = code

    def get_headers(self, environ=None):
        headers = {'Location': self.url}
        headers.update(super(Redirect, self).get_headers(environ))
        return headers


SUBSCRIPTION_LIST_FILENAME_PATTERN = re.compile(
    r'/subscriptions\.[-a-z0-9_.]+\.xml$'
)


def is_linkable(contents):
    if not contents:
        return 'create'
    sessions = any(content['path'].endswith('/.sessions')
                   for content in contents if content['is_dir'])
    linkable = sessions and any(
        SUBSCRIPTION_LIST_FILENAME_PATTERN.search(content['path'])
        for content in contents if not content['is_dir']
    )
    if linkable:
        return 'link'


def get_dropbox_path(path, client=None):
    if client is None:
        client = get_client()
    result = client.metadata(path)
    if not (result.get('is_dir') and
                    result.get('path').lower() == path.lower()):
        raise BadRequest()
    return result


@mod.route('/folders/', defaults={'path': ''})
@mod.route('/folders/<path:path>/')
def browse_folder(path):
    result = get_dropbox_path('/' + path)
    contents = result.get('contents', [])
    folders = [content['path'].rsplit('/', 1)[-1]
               for content in contents if content['is_dir']]
    folders = [name for name in folders if not name.startswith('.')]
    folders.sort()
    up_path = result['path'].rsplit('/', 1)[0][1:]
    return render_template('dropbox/browse_folders.html',
                           path=path,
                           up_path=up_path,
                           folders=folders,
                           linkable=is_linkable(contents))


@mod.route('/folders/', defaults={'path': ''}, methods=['PUT'])
@mod.route('/folders/<path:path>/', methods=['PUT'])
def link_repository(path):
    client = get_client()
    result = get_dropbox_path('/' + path, client)
    contents = result['contents']
    if not is_linkable(contents):
        raise BadRequest()
    set_config('dropbox_path', '/{0}/'.format(path) if path else '/')
    from .repository import pull_from_dropbox
    defer(pull_from_dropbox)
    return redirect(url_for('.wait_sync'))


@mod.route('/folders/', defaults={'path': ''}, methods=['POST'])
@mod.route('/folders/<path:path>/', methods=['POST'])
def make_folder(path):
    client = get_client()
    dir_path = (path and '/' + path) + '/' + request.form['name']
    try:
        client.file_create_folder(dir_path)
    except ErrorResponse as e:
        abort(e.status)
    return redirect(url_for('.browse_folder', path=dir_path[1:]))


@mod.route('/sync/')
def wait_sync():
    last_sync = get_config('dropbox_last_sync')
    if last_sync:
        return 'TODO: complete!'
    try:
        completed, total = get_config('dropbox_sync_progress')
    except TypeError:
        completed, total = 0, 1
    ratio = fractions.Fraction(completed, total)
    return render_template('dropbox/wait_sync.html', ratio=ratio)


@mod.route('/auth/')
def start_auth():
    auth_flow = get_auth_flow()
    authorize_url = auth_flow.start()
    return render_template('dropbox/start_auth.html',
                           authorize_url=authorize_url,
                           error=request.args.get('error'))


@mod.route('/callback/')
def finish_auth():
    auth_flow = get_auth_flow()
    try:
        access_token, user_id, _ = auth_flow.finish(request.args)
    except DropboxOAuth2Flow.BadRequestException:
        raise BadRequest()
    except DropboxOAuth2Flow.BadStateException:
        return redirect(url_for('.start_auth'))
    except DropboxOAuth2Flow.NotApprovedException:
        return redirect(url_for('.start_auth', error='not-approved'))
    except (DropboxOAuth2Flow.CsrfException,
            DropboxOAuth2Flow.ProviderException) as e:
        logging.getLogger(__name__ + '.finish_auth').exception(e)
        return Forbidden()
    set_config('dropbox_access_token', access_token)
    set_config('dropbox_user_id', user_id)
    client = get_client()
    account_info = client.account_info()
    return render_template('dropbox/finish_auth.html',
                           account_info=account_info)


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


@mod.route('/webhook/', methods=['GET', 'POST'])
def webhook():
    if request.method.upper() == 'GET':
        return request.args.get('challenge', '')
    app_secret = get_config('dropbox_app_secret')
    user_id = get_config('dropbox_user_id')
    if app_secret is None:
        raise Forbidden()
    expected = hmac.new(app_secret, request.data, hashlib.sha256).hexdigest()
    signature = request.headers.get('X-Dropbox-Signature')
    if expected != signature:
        raise Forbidden()
    if user_id not in set(request.json['delta']['users']):
        raise Forbidden()
    from .repository import pull_from_dropbox
    defer(pull_from_dropbox)
