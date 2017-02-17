#!/usr/bin/python
#
# Copyright (C) CloudOps Inc.
#
# This program is free software; you can redistribute it and/or modify 
# it under the terms of the GNU Lesser General Public License as published 
# by the Free Software Foundation; version 2.1 only.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA

import os

try:
    import simplejson as json
except:
    import json



class LvmConfigParser(object):
    """ Class which parses the LVM metadata. It uses the grammer given at
    http://linux.die.net/man/5/lvm.conf There are still some assumptions on the
    format of the data that is provided. Notably, sections start and end on a
    new line. i.e '<key> { ' and '}' will always occur on a new line 
    """

    ASSIGNMENT = 1
    DICT_START = 2
    DICT_END = 3

    def __init__(self, config_dict=None):

        self.out_str = ""

        self.root = {}
        if config_dict:
            self.root = config_dict

        self.cur_entry = self.root
        self.prev_entries = list()

        self.current_line = 0

        self.parse_callbacks = {

            LvmConfigParser.ASSIGNMENT: self._parseAssignment,
            LvmConfigParser.DICT_START: self._parseDictStart,
            LvmConfigParser.DICT_END: self._parseDictEnd,
        }

    def toConfigString(self):
        self._toString(self.root, 0)
        return self.out_str

    def toDict(self):
        return self.root

    def parse(self, config_file):

        fd = open(config_file)
        config_data = fd.readlines()
        clean_config = self._removeComments(config_data)
        fd.close()
        self._parse(clean_config)

    def _removeComments(self, config_list):

        clean_lines = []
        for line in config_list:
            line = line.strip()
            comment_idx = line.find('#')
            if comment_idx >= 0:
                line = line[:comment_idx]
            if len(line):
                clean_lines.append(line)

        return clean_lines

    def _getLineType(self, line):

        if line.find('=') >= 0:
            return LvmConfigParser.ASSIGNMENT
        elif line.endswith('{'):
            return LvmConfigParser.DICT_START
        elif line.endswith('}'):
            return LvmConfigParser.DICT_END

        assert "Parse type not found for %s" % line

    def _parse(self, lines):

        while self.current_line < len(lines):
            parse_type = self._getLineType(lines[self.current_line])
            self.parse_callbacks[parse_type](lines)

    def _parseAssignment(self, lines):

        line = lines[self.current_line]
        key, value = line.split('=')

        key = key.strip()
        value = value.strip()

        if value == '[':  # array spanning multiple lines
            while True:
                self.current_line += 1
                line = lines[self.current_line].strip()
                value += line
                if line == ']':
                    break

        self.cur_entry[key] = json.loads(value)
        self.current_line += 1

    def _parseDictStart(self, lines):

        line = lines[self.current_line]
        key, _ = line.split('{')
        key = key.strip()

        self.cur_entry[key] = {}
        self.prev_entries.append(self.cur_entry)

        self.cur_entry = self.cur_entry[key]
        self.current_line += 1

    def _parseDictEnd(self, lines):
        self.cur_entry = self.prev_entries.pop()
        self.current_line += 1

    def _toString(self, data, indent):
        indent_sp = '\t' * indent

        if type(data) == dict:
            for key in data:
                if type(data[key]) == dict:
                    self.out_str += indent_sp + "%s {\n" % key
                else:
                    self.out_str += indent_sp + "%s = " % key

                self._toString(data[key], indent + 1)

                if type(data[key]) == dict:
                    self.out_str += indent_sp + "}\n"
                else:
                    self.out_str += indent_sp + "\n"

        elif type(data) == list:
            self.out_str += "["
            for v in data:
                self._toString(v, indent)
                self.out_str += " , "

            # remove trailing comma for non-empty lists
            if len(data):
                self.out_str = self.out_str[:-3]
            self.out_str += "]\n"

        elif type(data) == str:
            self.out_str += '"%s"' % data

        else:
            self.out_str += "%s" % data


def gen_lvm_uuid():
    """
    Generates a random UUID used by LVM
    :return: a random UUID string
    """

    LEN = 32
    _c = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!#"
    groups = [6, 10, 14, 18, 22, 26, 32]  # lengths after with to insert a '-'
    group_idx = 0

    rand_bytes = os.urandom(LEN)
    uuid = ""

    for i in range(0, LEN):
        uuid += _c[ord(rand_bytes[i]) % (len(_c) - 3)]
        if i == groups[group_idx] - 1:
            group_idx += 1
            uuid += '-'

    return uuid[:-1]  # remove trailing '-'
