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

import datetime
import operator
import re
import rfc822
import shutil

from google.appengine.api.files import finalize, open as fopen
from google.appengine.api.files.blobstore import create, get_blob_key
from google.appengine.ext.blobstore import BlobInfo, BlobReferenceProperty
from google.appengine.ext.db import (DateTimeProperty, Model, Key,
                                     StringProperty,
                                     create_transaction_options,
                                     run_in_transaction_options)
from google.appengine.ext.deferred import defer
from libearth.repository import Repository, RepositoryKeyError

from .config import get_config, set_config
from .dropbox import get_client

__all__ = 'DataStoreRepository', 'Slot', 'pull_from_dropbox'


class DataStoreRepository(Repository):
    """Earth Reader repository that stores data into the Google App Engine
    powered data store, and then synchronizes data to Dropbox in background.

    """

    @classmethod
    def from_url(cls, url):
        return cls()

    def to_url(self, scheme):
        super(DataStoreRepository, self).to_url(scheme)
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
        with fopen(filename, 'ab') as f:
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
        run_in_transaction_options(create_transaction_options(xg=True), txn)
        defer(push_to_dropbox, db_key)

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
    rev = StringProperty()
    synced_at = DateTimeProperty()
    updated_at = DateTimeProperty(required=True, auto_now_add=True)

    def is_dir(self):
        return self.blob is None

    def __repr__(self):
        return '<RepositoryKey {0!r}>'.format(self.path)


def get_dropbox_client():
    client = get_client(redirect_on_fail=False)
    if client is None or not get_config('dropbox_path'):
        set_config('dropbox_access_token', None)
        set_config('dropbox_user_id', None)
        set_config('dropbox_delta_cursor', None)
        set_config('dropbox_path', None)
        return
    return client


def parse_rfc2822(rfc2822):
    time_tuple = rfc822.parsedate_tz(rfc2822)
    timestamp = rfc822.mktime_tz(time_tuple)
    return datetime.datetime.utcfromtimestamp(timestamp)


def push_to_dropbox(slot_key):
    client = get_dropbox_client()
    if client is None:
        return
    slot = Slot.get(slot_key)
    f = slot.blob.open()
    response = client.put_file('/' + slot.key().name(), f,
                               overwrite=True,
                               parent_rev=slot.rev)
    f.close()
    rfc2822 = response['modified']
    slot.synced_at = parse_rfc2822(rfc2822)
    slot.rev = response.rev
    slot.put()


def pull_from_dropbox():
    client = get_dropbox_client()
    if client is None:
        return
    path_prefix = get_config('dropbox_path')
    cursor = get_config('dropbox_delta_cursor')
    last_sync = get_config('dropbox_last_sync') or datetime.datetime(2000, 1, 1)
    while 1:
        result = client.delta(cursor, path_prefix=path_prefix.rstrip('/'))
        for path, metadata in result['entries']:
            if metadata and metadata['is_dir']:
                continue
            repo_key = path[len(path_prefix):].split('/')
            db_key = make_db_key(repo_key)
            if metadata:
                rev = metadata['rev']
                modified_at = parse_rfc2822(metadata['modified'])
                last_sync = max(modified_at, last_sync)
                filename = create(mime_type='text/xml')
                with fopen(filename, 'ab') as dst:
                    src = client.get_file(path, rev=rev)
                    shutil.copyfileobj(src, dst)
                finalize(filename)
                blob_key = get_blob_key(filename)
                blob_info = BlobInfo.get(blob_key)
                def txn():
                    slot = Slot.get(db_key)
                    if slot is None:
                        slot = Slot(
                            db_key=db_key,
                            blob=blob_info,
                            rev=rev,
                            updated_at=modified_at,
                            synced_at=modified_at
                        )
                    else:
                        slot.blob.delete()
                        slot.blob = blob_info
                        slot.rev = rev
                        slot.updated_at = modified_at
                        slot.synced_at = modified_at
                    slot.put()
                run_in_transaction_options(create_transaction_options(xg=True),
                                           txn)
            else:
                slot = Slot.get(db_key)
                if slot is not None:
                    slot.delete()
        cursor = result['cursor']
        set_config('dropbox_delta_cursor', cursor)
        if not result['has_more']:
            break
    set_config('dropbox_last_sync', last_sync)
