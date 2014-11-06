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

from google.appengine.api.app_identity import get_application_id
from libearth.session import Session
from libearth.stage import Stage

from .repository import DataStoreRepository

__all__ = 'get_session', 'get_stage'


def get_session():
    session_id = 'ergae-{0}'.format(get_application_id())
    return Session(session_id)


def get_stage():
    repository = DataStoreRepository()
    session = get_session()
    return Stage(session, repository)
