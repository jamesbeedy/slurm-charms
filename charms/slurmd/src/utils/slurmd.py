#!/usr/bin/python3
# Copyright 2023 Canonical Ltd.
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

"""Manage the internal slurmd daemon on Juju machines.

This module also provides a wrapper for starting the slurmd service using systemd.
"""

import datetime
import logging
import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import charms.operator_libs_linux.v1.systemd as systemd  # type: ignore [import-untyped]

_logger = logging.getLogger(__name__)


def start() -> None:
    """Start slurmd service."""
    systemd.service_start("slurmd")


def stop() -> None:
    """Stop slurmd service."""
    systemd.service_stop("slurmd")


def restart() -> None:
    """Restart slurmd service."""
    systemd.service_restart("slurmd")


def override_default(host: str) -> None:
    """Override the /etc/default/slurmd file.

    Args:
        host: Hostname of slurmctld service.
    """
    _logger.debug("Overriding /etc/default/slurmd.")
    Path("/etc/default/slurmd").write_text(
        textwrap.dedent(
            f"""
            SLURMD_OPTIONS="--conf-server {host}:6817"
            PYTHONPATH={Path.cwd() / "lib"}
            """
        ).strip()
    )


def override_service() -> None:
    """Override the default slurmd systemd service file.

    Notes:
        This method makes an invokes `systemd daemon-reload` after writing
        the overrides.conf file for slurmd. This invocation will reload
        all systemd units on the machine.
    """
    _logger.debug("Overriding default slurmd service file")
    if not (override_dir := Path("/etc/systemd/system/slurmd.service.d")).is_dir():
        override_dir.mkdir()

    overrides = override_dir / "99-slurmd-charm.conf"
    overrides.write_text(
        textwrap.dedent(
            f"""
            [Unit]
            ConditionPathExists=

            [Service]
            Type=forking
            ExecStart=
            ExecStart=/usr/bin/python3 {__file__}
            LimitMEMLOCK=infinity
            LimitNOFILE=1048576
            TimeoutSec=900
            """
        ).strip()
    )
    systemd.daemon_reload()


