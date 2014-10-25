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

import operator
import re

from google.appengine.api.files import finalize, open as fopen
from google.appengine.api.files.blobstore import create, get_blob_key
from google.appengine.ext.blobstore import BlobInfo, BlobReferenceProperty
from google.appengine.ext.db import (DateTimeProperty, Model, Key,
                                     run_in_transaction)

from libearth.repository import Repository, RepositoryKeyError

__all__ = 'DataStoreRepository', 'Slot'


class DataStoreRepository(Repository):
    """Earth Reader repository that stores data into the Google App Engine
    powered data store, and then synchronizes data to Dropbox in background.

    """

    @classmethod
    def from_url(cls, url):
        return cls()

    def to_url(self, scheme):
        super(DataStoreRepository, self).to_url(self, scheme)
        return scheme + '://'

    def read(self, key):
        super(DataStoreRepository, self).read(key)
        db_key = make_db_key(key)
        slot = Slot.get(db_key)
        if slot is None:
            raise RepositoryKeyError(key)
        return slot.blob.open()

    def write(self, key, iterable):
        super(DataStoreRepository, self).write(key, iterable)
        db_key = make_db_key(key)
        filename = create(mime_type='text/xml')
        with fopen(filename, 'wb') as f:
            for chunk in iterable:
                f.write(chunk)
        finalize(filename)
        blob_key = get_blob_key(filename)
        blob_info = BlobInfo.get(blob_key)

        def txn():
            slot = Slot.get(db_key)
            if slot is None:
                slot = Slot(key=db_key, blob=blob_info)
            else:
                slot.blob.delete()
                slot.blob = blob_info
            slot.put()
        run_in_transaction(txn)

    def exists(self, key):
        super(DataStoreRepository, self).exists(key)
        return Slot.get(make_db_key(key)) is not None

    def list(self, key):
        super(DataStoreRepository, self).list(key)
        parent_db_key = make_db_key(key)
        query = Slot.all().ancestor(parent_db_key)
        db_keys = query.run(keys_only=True)
        if not db_keys and Slot.get(parent_db_key) is None:
            raise RepositoryKeyError(key)
        return frozenset(KEY_LAST_PART_PATTERN.match(db_key.name()).group(1)
                         for db_key in db_keys)


KEY_LAST_PART_PATTERN = re.compile(r'(?:^|/)([^/]+)$')


def make_db_key(key):
    path = reduce(
        operator.add,
        (('Slot', '/'.join(key[:i + 1])) for i in range(len(key))),
        ()
    )
    return Key.from_path(*path)


class Slot(Model):

    blob = BlobReferenceProperty()
    synced_at = DateTimeProperty()
    updated_at = DateTimeProperty(required=True, auto_now_add=True)

    def is_dir(self):
        return self.blob is None

    def __repr__(self):
        return '<RepositoryKey {0!r}>'.format(self.path)
