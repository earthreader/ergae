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

from google.appengine.api.memcache import get, set
from google.appengine.ext.db import Model
from google.appengine.ext.ndb import PickleProperty

__all__ = 'Config', 'get_config', 'set_config'


def get_config(key):
    value = get(key, namespace='config')
    if value:
        return value
    pair = Pair.get_by_key_name(key)
    return pair and pair.value


def set_config(key, value):
    set(key, value, namespace='config')
    Pair.get_or_insert(key, value=value)


class Pair(Model):
    """Key-value pair."""

    value = PickleProperty()
