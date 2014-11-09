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

from flask import Blueprint, g, redirect, render_template, request, url_for
from google.appengine.api.users import get_current_user
from libearth.defaults import get_default_subscriptions
from libearth.feed import Person
from libearth.subscribe import SubscriptionList

from .config import get_config
from .stage import get_stage

__all__ = 'mod',


mod = Blueprint('reader', __name__)


@mod.before_request
def setup_stage():
    if not (get_config('dropbox_app_key') and get_config('dropbox_app_secret')):
        return redirect(url_for('dropbox.appkey_form'))
    elif not (get_config('dropbox_access_token') and
              get_config('dropbox_user_id')):
        return redirect(url_for('dropbox.start_auth'))
    elif not (get_config('dropbox_path') and get_config('dropbox_last_sync')):
        return redirect(url_for('dropbox.browse_folder'))
    g.stage = get_stage()
    with g.stage:
        subscriptions = g.stage.subscriptions
        exceptions = {'reader.initialize_subscriptions_form',
                      'reader.initialize_subscriptions'}
        if request.endpoint not in exceptions and \
           not (subscriptions and subscriptions.head and subscriptions.owner):
            return redirect(url_for('.initialize_subscriptions_form'))


@mod.route('/subscriptions/initialize/')
def initialize_subscriptions_form():
    current_user = get_current_user()
    default_owner = Person(name=current_user.nickname(),
                           email=current_user.email())
    default_title = None
    with g.stage:
        subscriptions = g.stage.subscriptions
        if subscriptions is not None:
            default_owner = subscriptions.owner
            default_title = subscriptions.title
    default_title_format = u'{name}\u2019s Subscriptions'
    if default_title is None:
        default_title = default_title_format.format(name=default_owner.name)
    return render_template('reader/initialize_subscriptions_form.html',
                           default_title_format=default_title_format,
                           default_owner=default_owner,
                           default_title=default_title)


@mod.route('/subscriptions/initialize/', methods=['POST'])
def initialize_subscriptions():
    def form(field):
        value = request.form.get(field)
        return value and value.strip()
    owner_name = form('owner_name')
    owner_email = form('owner_email')
    owner_uri = form('owner_uri')
    if owner_name:
        owner = Person(name=owner_name,
                       email=owner_email or None,
                       uri=owner_uri or None)
    else:
        owner = None
    title = form('title')
    with g.stage:
        subscriptions = g.stage.subscriptions
        if subscriptions is None:
            subscriptions = get_default_subscriptions()
            subscriptions.owner = None
            subscriptions.title = None
        if owner:
            subscriptions.owner = owner
        if title:
            subscriptions.title = title
        g.stage.subscriptions = subscriptions
    return 'Success!'
