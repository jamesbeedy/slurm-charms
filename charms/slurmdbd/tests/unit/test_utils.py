#!/usr/bin/env python3
# Copyright (c) 2025 Vantage Compute Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test functions in utils.py."""

# test_utils.py
# test_utils.py

import textwrap
from unittest.mock import patch

import pytest
from utils import parse_user_supplied_parameters


def test_parse_valid_config():
    config = textwrap.dedent(
        """
        StorageType=accounting_storage/slurmdbd
        LogFile=/var/log/slurm/slurmdbd.log
        """
    )
    expected = {
        "StorageType": "accounting_storage/slurmdbd",
        "LogFile": "/var/log/slurm/slurmdbd.log",
    }
    result = parse_user_supplied_parameters(config)
    assert result == expected


def test_parse_with_comments_and_blank_lines():
    config = textwrap.dedent(
        """
        # This is a comment
        StorageType=accounting_storage/slurmdbd

        LogFile=/var/log/slurm/slurmdbd.log
        # Another comment
        """
    )
    expected = {
        "StorageType": "accounting_storage/slurmdbd",
        "LogFile": "/var/log/slurm/slurmdbd.log",
    }
    result = parse_user_supplied_parameters(config)
    assert result == expected


def test_parse_empty_config():
    config = ""
    result = parse_user_supplied_parameters(config)
    assert result == {}


def test_parse_malformed_line_raises_index_error():
    config = textwrap.dedent(
        """
        ValidKey=ValidValue
        MalformedLineWithoutEquals
        """
    )

    with patch("utils.logger") as mock_logger:
        with pytest.raises(IndexError):
            parse_user_supplied_parameters(config)
        assert mock_logger.error.called
        assert "Could not parse user supplied parameters" in mock_logger.error.call_args[0][0]


def test_parse_handles_only_malformed_line():
    config = "BadLineWithoutEquals"
    with patch("utils.logger") as mock_logger:
        with pytest.raises(IndexError):
            parse_user_supplied_parameters(config)
        assert mock_logger.error.called
