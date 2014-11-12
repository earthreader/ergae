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
import hashlib
import logging
import operator
import random
import re
import rfc822
import time

from google.appengine.api.files import finalize, open as fopen
from google.appengine.api.files.blobstore import create, get_blob_key
from google.appengine.api.memcache import delete, get, set as put
from google.appengine.ext.blobstore import BlobInfo, BlobReferenceProperty
from google.appengine.ext.db import (DateTimeProperty, EntityNotFoundError,
                                     IntegerProperty, Model, Key,
                                     StringProperty,
                                     create_transaction_options,
                                     run_in_transaction_options)
from google.appengine.ext.deferred import defer
import itertools
from libearth.repository import Repository, RepositoryKeyError

from .config import get_config, set_config
from .dropbox import get_client

__all__ = ('INCOMING_BYTES_LIMIT', 'OUTGOING_BYTES_LIMIT',
           'DataStoreRepository', 'Slot',
           'make_db_key', 'pull_from_dropbox', 'push_to_dropbox')


INCOMING_BYTES_LIMIT = 31 * 1000 * 1000  # 31MB
OUTGOING_BYTES_LIMIT = 9 * 1000 * 1000  # 9MB
CACHE_BYTES_LIMIT = 1000 * 1000 - 256 - 96  # 1MB - cache key size - 96 bytes


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
        cache_key = make_cache_key(key)
        cached = get(cache_key, namespace='slot')
        if cached is not None:
            return cached,
        db_key = make_db_key(key)
        slot = Slot.get(db_key)
        if slot is None:
            raise RepositoryKeyError(key)
        blob = slot.blob.open()
        if slot.blob.size < CACHE_BYTES_LIMIT:
            put(cache_key, blob.read(), namespace='slot')
            blob.seek(0)
        return blob

    def write(self, key, iterable):
        super(DataStoreRepository, self).write(key, iterable)
        size = 0
        cache_value_buffer = []
        for chunk in iterable:
            size += len(chunk)
            cache_value_buffer.append(chunk)
            if size >= CACHE_BYTES_LIMIT:
                break
        else:
            cache_key = make_cache_key(key)
            cache_value = ''.join(cache_value_buffer)
            put(cache_key, cache_value, namespace='slot')
            defer(put_slot, key, cache_value_buffer)
            return
        iterable = itertools.chain(cache_value_buffer, iterable)
        put_slot(key, iterable)

    def exists(self, key):
        super(DataStoreRepository, self).exists(key)
        if get(make_cache_key(key), namespace='slot') is not None:
            return True
        list_cache = get(make_cache_key(key[:-1]), namespace='list')
        if list_cache is None:
            return tuple(key) in list_cache
        return Slot.get(make_db_key(key)) is not None

    def list(self, key):
        super(DataStoreRepository, self).list(key)
        cache_key = make_cache_key(key[:-1])
        list_cache = get(cache_key, namespace='list')
        if list_cache is not None:
            return list_cache
        if key:
            parent_db_key = make_db_key(key)
            db_keys = Slot.all().ancestor(parent_db_key).run(keys_only=True)
            if key and not db_keys and Slot.get(parent_db_key) is None:
                raise RepositoryKeyError(key)
        else:
            db_keys = Slot.all().filter('depth <=', 1).run(keys_only=True)
        key_names = [db_key.name() for db_key in db_keys]
        children = frozenset(KEY_LAST_PART_PATTERN.match(key_name).group(1)
                             for key_name in key_names)
        put(cache_key, children, namespace='list')
        return children


KEY_LAST_PART_PATTERN = re.compile(r'(?:^|/)([^/]+)$')


def make_cache_key(key):
    hash_ = hashlib.sha256()
    for k in key:
        hash_.update('/')
        hash_.update(k.encode('utf-8') if isinstance(k, unicode) else k)
    return hash_.hexdigest()


def make_db_key(key):
    path = reduce(
        operator.add,
        (('Slot', '/'.join(key[:i + 1])) for i in range(len(key))),
        ()
    )
    return Key.from_path(*path)


class Slot(Model):

    depth = IntegerProperty(required=True)
    blob = BlobReferenceProperty()
    rev = StringProperty()
    synced_at = DateTimeProperty()
    updated_at = DateTimeProperty(required=True, auto_now_add=True)

    def is_dir(self):
        return self.blob is None

    def __repr__(self):
        return '<RepositoryKey {0!r}>'.format(self.path)


def put_slot(key, iterable):
    db_key = make_db_key(key)
    filename = create(mime_type='text/xml')
    size = 0
    with fopen(filename, 'ab') as f:
        for chunk in iterable:
            f.write(chunk)
            size += len(chunk)
    finalize(filename)
    blob_key = get_blob_key(filename)
    blob_info = BlobInfo.get(blob_key)
    assert blob_info.size == size, (
        'blob_info.size = {0!r}, size = {1!r}'.format(blob_info.size, size)
    )
    assert isinstance(blob_info, BlobInfo)
    now = datetime.datetime.utcnow()
    cache_key = make_cache_key(key)
    list_cache_key = make_cache_key(key[:-1])

    def txn():
        delete(cache_key, namespace='slot')
        delete(list_cache_key, namespace='list')
        slot = Slot.get(db_key)
        if slot is None:
            slot = Slot(
                depth=len(key),
                key=db_key,
                blob=blob_info,
                updated_at=now
            )
        else:
            assert isinstance(slot.blob, BlobInfo)
            slot.blob.delete()
            slot.blob = blob_info
            slot.updated_at = now
        slot.put()
        delete(list_cache_key, namespace='list')

    run_in_transaction_options(create_transaction_options(xg=True), txn)
    defer(push_to_dropbox, db_key, now)


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


def push_to_dropbox(slot_key, now):
    logger = logging.getLogger(__name__ + '.push_to_dropbox')
    client = get_dropbox_client()
    dropbox_path = get_config('dropbox_path')
    if client is None or dropbox_path is None:
        return
    blob_size = None
    while blob_size is None:
        slot = Slot.get(slot_key)
        dropbox_filename = dropbox_path + slot.key().name()
        if slot.updated_at < now:
            logger.info('%s was updated (at %s) after %s',
                        dropbox_filename, slot.updated_at, now)
            return
        logger.info('pushing %s to dropbox', dropbox_filename)
        f = slot.blob.open()
        try:
            blob_size = slot.blob.size
        except EntityNotFoundError:
            logger.info('failed to load %s from dirty buffer; retry...',
                        dropbox_filename)
            time.sleep(random.randrange(1, 5))
    if blob_size <= OUTGOING_BYTES_LIMIT:
        response = client.put_file(dropbox_filename, f,
                                   overwrite=True,
                                   parent_rev=slot.rev)
    else:
        uploader = client.get_chunked_uploader(f, blob_size)
        while uploader.offset < blob_size:
            uploader.upload_chunked(OUTGOING_BYTES_LIMIT)
        uploader.finish(dropbox_filename, overwrite=True, parent_rev=slot.rev)
    f.close()
    rfc2822 = response['modified']
    slot.synced_at = parse_rfc2822(rfc2822)
    slot.rev = response['rev']
    slot.put()


def pull_from_dropbox():
    client = get_dropbox_client()
    if client is None:
        return
    path_prefix = get_config('dropbox_path')
    cursor = get_config('dropbox_delta_cursor')
    last_sync = get_config('dropbox_last_sync') or datetime.datetime(2000, 1, 1)
    first = cursor is None
    if first:
        set_config('dropbox_sync_progress', (0, 1))
    entries = []
    while 1:
        result = client.delta(cursor, path_prefix=path_prefix.rstrip('/'))
        entries.extend(
            (path, metadata)
            for path, metadata in result['entries']
            if not (metadata and metadata['is_dir'])
        )
        cursor = result['cursor']
        set_config('dropbox_delta_cursor', cursor)
        if not result['has_more']:
            break
    for i, (path, metadata) in enumerate(entries):
        repo_key = path[len(path_prefix):].split('/')
        cache_key = make_cache_key(repo_key)
        list_cache_key = make_cache_key(repo_key[:-1])
        db_key = make_db_key(repo_key)
        if metadata:
            rev = metadata['rev']
            modified_at = parse_rfc2822(metadata['modified'])
            last_sync = max(modified_at, last_sync)
            filename = create(mime_type='text/xml')
            cache_value = None
            with fopen(filename, 'ab') as dst:
                for offset in xrange(0, metadata['bytes'],
                                     INCOMING_BYTES_LIMIT):
                    src = client.get_file(path,
                                          rev=rev,
                                          start=offset,
                                          length=offset)
                    while 1:
                        chunk = src.read(10240)
                        if chunk:
                            dst.write(chunk)
                        else:
                            break
                dst_size = dst.tell()
                if dst_size < CACHE_BYTES_LIMIT:
                    dst.seek(0)
                    cache_value = dst.read()
                    dst.seek(dst_size)
            finalize(filename)
            blob_key = get_blob_key(filename)
            blob_info = BlobInfo.get(blob_key)
            def txn():
                delete(cache_key, namespace='slot')
                delete(list_cache_key, namespace='list')
                slot = Slot.get(db_key)
                if slot is None:
                    slot = Slot(
                        depth=len(repo_key),
                        key=db_key,
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
                if cache_value is not None:
                    put(cache_key, cache_value, namespace='slot')
                delete(list_cache_key, namespace='list')
            run_in_transaction_options(create_transaction_options(xg=True),
                                       txn)
        else:
            slot = Slot.get(db_key)
            if slot is not None:
                slot.delete()
                delete(cache_key, namespace='slot')
        delete(list_cache_key, namespace='list')
        if first:
            set_config('dropbox_sync_progress', (i + 1, len(entries)))
    set_config('dropbox_last_sync', last_sync)
