# ------------------------------------------------------------------------------
#
# Project: EOxServer <http://eoxserver.org>
# Authors: Fabian Schindler <fabian.schindler@eox.at>
#
# ------------------------------------------------------------------------------
# Copyright (C) 2019 EOX IT Services GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies of this Software or works derived from this Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
# ------------------------------------------------------------------------------

import json

from django.conf import settings
from django.utils.module_loading import import_string
from swiftclient.service import get_conn

from swiftclient.client import get_auth_keystone

from eoxserver.backends.config import DEFAULT_EOXS_STORAGE_AUTH_HANDLERS


class StorageAuthVSIContext(object):
    def __init__(self, env_vars):
        self.env_vars = env_vars

    def __enter__(self):
        pass

    def __exit__(self, type, value, traceback):
        pass

class BaseStorageAuthHandler(object):
    def __init__(self, url, parameters):
        self.url = url
        self.parameters = parameters

    def get_vsi_env(self):
        raise NotImplementedError

class KeystoneStorageAuthHandler(BaseStorageAuthHandler):
    name = 'keystone'

    def _get_url_and_token(self):
        url, token = self.get_auth()
        return url, token

    def get_auth(self):
        os_options = {
            key: self.parameters.get(key)
            for key in [
                'tenant_id', 'auth_token', 'service_type', 'endpoint_type',
                'tenant_name', 'object_storage_url', 'region_name',
                'service_username', 'service_project_name', 'service_key'
            ]
        }

        return get_auth_keystone(
            self.url,
            user=self.parameters.get('username'),
            key=self.parameters.get('password'),
            os_options=os_options,
        )

    def get_vsi_env(self):
        url, token = self._get_url_and_token()
        return {
            'SWIFT_STORAGE_URL': url,
            'SWIFT_AUTH_TOKEN': token,
        }



STORAGE_AUTH_HANDLERS = None


def _setup_storage_auth_handlers():
    """ Setup the storage handlers. Uses the ``EOXS_STORAGE_AUTH_HANDLERS``
        setting which falls back to the ``DEFAULT_EOXS_STORAGE_AUTH_HANDLERS``
    """
    global STORAGE_AUTH_HANDLERS
    specifiers = getattr(
        settings, 'EOXS_STORAGE_AUTH_HANDLERS', DEFAULT_EOXS_STORAGE_AUTH_HANDLERS
    )
    STORAGE_AUTH_HANDLERS = [import_string(specifier) for specifier in specifiers]


def get_handlers():
    if STORAGE_AUTH_HANDLERS is None:
        _setup_storage_auth_handlers()

    return STORAGE_AUTH_HANDLERS


def get_handler_by_test(locator):
    """ Test the given locator with the configured storage handlers and return the stora
    """
    if STORAGE_AUTH_HANDLERS is None:
        _setup_storage_auth_handlers()

    for storage_auth_handler_cls in STORAGE_AUTH_HANDLERS:
        try:
            if storage_auth_handler_cls.test(locator):
                return storage_auth_handler_cls(locator)
        except AttributeError:
            pass


def get_handler_class_by_name(name):
    if STORAGE_AUTH_HANDLERS is None:
        _setup_storage_auth_handlers()

    for storage_auth_handler_cls in STORAGE_AUTH_HANDLERS:
        try:
            if storage_auth_handler_cls.name == name:
                return storage_auth_handler_cls
        except AttributeError:
            pass


def get_handler_class_for_model(storage_auth_model):
    return get_handler_class_by_name(storage_auth_model.storage_auth_type)


def get_handler_for_model(storage_auth_model):
    return get_handler_class_for_model(
        storage_auth_model
    )(storage_auth_model.url, json.loads(storage_auth_model.auth_parameters))
