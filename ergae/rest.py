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

import io
import json

from dropbox.rest import (SDK_VERSION, ErrorResponse, RESTSocketError,
                          params_to_urlencoded, RESTClient)
from google.appengine.api.urlfetch import fetch
from google.appengine.api.urlfetch_errors import (DownloadError,
                                                  SSLCertificateError)
from werkzeug.http import HTTP_STATUS_CODES

__all__ = 'RestClient', 'RestClientObject', 'RestErrorResponse'


class RestErrorResponse(ErrorResponse):

    def __init__(self, response):
        self.status = response.status_code
        self.reason = HTTP_STATUS_CODES[response.status_code]
        self.body = response.content
        self.headers = response.header_msg
        try:
            self.body = json.loads(self.body)
            self.error_msg = self.body.get('error')
            self.user_error_msg = self.body.get('user_error')
        except ValueError:
            self.error_msg = None
            self.user_error_msg = None


class RestClientObject(object):

    def request(self, method, url, post_params=None, body=None, headers=None,
                raw_response=False):
        post_params = post_params or {}
        headers = headers or {}
        headers['User-Agent'] = 'OfficialDropboxPythonSDK/' + SDK_VERSION
        if post_params:
            if body:
                raise ValueError(
                    'body parameter cannot be used with post_params parameter'
                )
            body = params_to_urlencoded(post_params)
            headers['Content-Type'] = 'application/x-www-form-urlencoded'

        if hasattr(body, 'getvalue'):
            body = str(body.getvalue())
        elif callable(getattr(body, 'read', None)):
            body = body.read()

        # Reject any headers containing newlines; the error from the server
        # isn't pretty.
        for key, value in headers.items():
            if isinstance(value, basestring) and '\n' in value:
                raise ValueError('headers should not contain newlines '
                                 '({0}: {1})'.format(key, value))

        try:
            # Grab a connection from the pool to make the request.
            # We return it to the pool when caller close() the response
            r = fetch(url, body,
                      method=method,
                      headers=headers,
                      validate_certificate=True)
        except DownloadError as e:
            raise RESTSocketError(url, e)
        except SSLCertificateError as e:
            raise RESTSocketError(url, 'SSL certificate error: ' + str(e))
        if r.status_code not in (200, 206):
            raise RestErrorResponse(r)
        return self.process_response(r, raw_response)

    def process_response(self, r, raw_response):
        if raw_response:
            return io.BytesIO(r.content)
        try:
            resp = json.loads(r.content)
        except ValueError:
            raise RestErrorResponse(r)
        return resp

    def GET(self, url, headers=None, raw_response=False):
        return self.request('GET', url,
                            headers=headers, raw_response=raw_response)

    def POST(self, url, params=None, headers=None, raw_response=False):
        return self.request(
            'POST', url,
            post_params=params or {},
            headers=headers,
            raw_response=raw_response
        )

    def PUT(self, url, body, headers=None, raw_response=False):
        return self.request(
            'PUT', url,
            body=body,
            headers=headers,
            raw_response=raw_response
        )


class RestClient(RESTClient):

    IMPL = RestClientObject()
