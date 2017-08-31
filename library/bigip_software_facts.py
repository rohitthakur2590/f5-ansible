#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2017 F5 Networks Inc.
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {
    'status': ['preview'],
    'supported_by': 'community',
    'metadata_version': '1.0'
}

DOCUMENTATION = '''
---
module: bigip_software_facts
short_description: Collect software facts from BIG-IP devices.
description:
  - Collect information about installed volumes, existing ISOs for images and hotfixes on the BIG-IP device.
version_added: "2.5"
options:
  include:
    description:
      - Type of information to collect.
    default: 
      - all
    choices:
      - all
      - image
      - hotfix
      - volume
  filter:
    description:
      - Filter responses based on the attribute and value provided. Valid filters are required to be in 
      C(key:value) format, with keys being one of the following: name, build, version, status, active.
notes:
   - Requires the f5-sdk Python package on the host. This is as easy as
     pip install f5-sdk
extends_documentation_fragment: f5
requirements:
  - f5-sdk
author:
  - Wojciech Wypior (@wojtek0806)
'''

EXAMPLES = '''
- name: Gather image facts filter on version
  bigip_software_facts:
      server: "lb.mydomain.com"
      user: "admin"
      password: "secret"
      include: "image"
      filter: "version:12.1.1"
  delegate_to: localhost
'''

RETURN = '''
images:
    description:
        List of base image ISOs that are present on the unit.
    returned: changed
    type: list of dict
    sample:
        images:
            - build: 0.0.184
              fileSize: 1997 MB,
              lastModified: Sun Oct  2 20:50:04 2016,
              name: BIGIP-12.1.1.0.0.184.iso,
              product: BIG-IP,
              version: 12.1.1
hotfixes:
    description:
        List of hotfix ISOs that are present on the unit.
    returned: changed
    type: list of dict
    sample:
        hotfixes:
            - build: 2.0.204
              fileSize: 1997 MB,
              lastModified: Sun Oct  2 20:50:04 2016,
              name: 12.1.1-hf2.iso,
              product: BIG-IP,
              version: 12.1.1   
volumes:     
    description:
        List the volumes present on device.
    returned: changed
    type: list of dict
    sample:
       volumes:
            - basebuild: 0.0.184,
              build: 0.0.184,
              name: HD1.2,
              product: BIG-IP,
              status: complete,
              version: 12.1.1              
'''


from ansible.module_utils.f5_utils import (
    AnsibleF5Client,
    AnsibleF5Parameters,
    HAS_F5SDK,
    F5ModuleError,
    iteritems
)


class Parameters(AnsibleF5Parameters):
    returnables = [
        'name', 'build', 'version', 'product',
        'lastModified', 'basebuild', 'status',
        'active', 'fileSize'
    ]

    @property
    def include(self):
        requested = self._values['include']
        valid = ['all', 'volume', 'image', 'hotfix']

        if not set(requested).issubset(set(valid)):
            raise F5ModuleError(
                'Include parameter may only be specified as one or more of the following: {0}'.format(', '.join(valid))
            )

        if 'all' in requested:
            return ['all']
        else:
            return requested

    @property
    def filter(self):
        requested = self._values['filter']
        keys = ['name', 'build', 'version', 'status', 'active']
        error = '"{0}" is not a valid filter format. Filters must have key:value format'.format(requested)
        if requested is None:
            return None

        if ':' not in requested:
            raise F5ModuleError(error)

        key, value = requested.split(':')

        if len(key) == 0 or len(value) == 0:
            raise F5ModuleError(error)

        if key not in keys:
            raise F5ModuleError('"{0}" is not a supported filter. '
                                'Supported key values are: {1}'.format(key, ', '.join(keys)))

        return key, value


class ModuleManager(object):
    def __init__(self, client):
        self.client = client
        self.want = Parameters(self.client.module.params)
        self.include = self.want.include

    def exec_module(self):
        if 'all' in self.include:
            names = ['image', 'hotfix', 'volume']
        else:
            names = self.include
        managers = [self.get_manager(name) for name in names]
        result = self.execute_managers(managers)
        return result

    def execute_managers(self, managers):
        results = dict(changed=False)
        for manager in managers:
            result = manager.exec_module()
            for k, v in iteritems(result):
                if k == 'changed':
                    if v is True:
                        results['changed'] = True
                else:
                    results[k] = v
        return results

    def get_manager(self, which):
        if 'image' == which:
            return ImageFactManager(self.client)
        if 'hotfix' == which:
            return HotfixFactManager(self.client)
        if 'volume' == which:
            return VolumeFactManager(self.client)


class BaseManager(object):
    def __init__(self, client):
        self.client = client
        self.want = Parameters(self.client.module.params)
        self.result = dict()
        self.filter = self.want.filter

    def exec_module(self):
        result = dict()
        facts = self.get_facts()
        result.update(**facts)
        result.update(dict(changed=True))
        return result

    def _filter_and_format_facts(self, fact):
        filtered = dict()
        listing = fact.attrs
        for k, v in listing.viewitems():
            if k in Parameters.returnables:
                filtered[str(k)] = str(v)
        return filtered

    def collection_parser(self, collection):
        output = list()
        if self.filter is None:
            for item in collection:
                output.append(self._filter_and_format_facts(item))
        else:
            bools = ['true', 'True', 'false', 'False']
            key, value = self.filter
            if value in bools:
                value = bool(value)
            for item in collection:
                if hasattr(item, key):
                    if getattr(item, key) == value:
                        output.append(self._filter_and_format_facts(item))
        return output


class ImageFactManager(BaseManager):

    def get_facts(self):
        to_return = dict()
        collection = self.get_facts_from_device()
        to_return['images'] = self.collection_parser(collection)
        return to_return

    def get_facts_from_device(self):
        images = self.client.api.tm.sys.software.images.get_collection()
        return images


class HotfixFactManager(BaseManager):

    def get_facts(self):
        to_return = dict()
        collection = self.get_facts_from_device()
        to_return['hotfixes'] = self.collection_parser(collection)
        return to_return

    def get_facts_from_device(self):
        hotfixes = self.client.api.tm.sys.software.hotfix_s.get_collection()
        return hotfixes


class VolumeFactManager(BaseManager):

    def get_facts(self):
        to_return = dict()
        collection = self.get_facts_from_device()
        to_return['volumes'] = self.collection_parser(collection)
        return to_return

    def get_facts_from_device(self):
        volumes = self.client.api.tm.sys.software.volumes.get_collection()
        return volumes


class ArgumentSpec(object):
    def __init__(self):
        self.supports_check_mode = True
        self.argument_spec = dict(
            include=dict(
                type='list',
                default=['all'],
            ),
            filter=dict()
        )
        self.f5_product_name = 'bigip'


def main():
    if not HAS_F5SDK:
        raise F5ModuleError("The python f5-sdk module is required")

    spec = ArgumentSpec()

    client = AnsibleF5Client(
        argument_spec=spec.argument_spec,
        supports_check_mode=spec.supports_check_mode,
        f5_product_name=spec.f5_product_name
    )

    try:
        mm = ModuleManager(client)
        results = mm.exec_module()
        client.module.exit_json(**results)
    except F5ModuleError as e:
        client.module.fail_json(msg=str(e))

if __name__ == '__main__':
    main()
