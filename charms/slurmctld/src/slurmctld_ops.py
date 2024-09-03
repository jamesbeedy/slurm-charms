# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""This module provides the SlurmctldManager."""

import logging
import os
import socket
import subprocess
import tempfile
from base64 import b64decode, b64encode
from grp import getgrnam
from pathlib import Path
from pwd import getpwnam
from typing import Optional

import distro
from constants import (
    MUNGE_SYSTEMD_SERVICE_FILE,
    SLURM_GROUP,
    SLURM_USER,
    SLURMCTLD_SYSTEMD_SERVICE_FILE,
    UBUNTU_HPC_PPA_KEY,
)
from Crypto.PublicKey import RSA
from slurm_conf_editor import slurm_conf_as_string

import charms.operator_libs_linux.v0.apt as apt
import charms.operator_libs_linux.v1.systemd as systemd

logger = logging.getLogger()


def is_container() -> bool:
    """Determine if we are running in a container."""
    container = False
    try:
        container = subprocess.call(["systemd-detect-virt", "--container"]) == 0
    except subprocess.CalledProcessError as e:
        logger.error(e)
        raise (e)
    return container


def _get_slurm_user_uid_and_slurm_group_gid():
    """Return the slurm user uid and slurm group gid."""
    slurm_user_uid = getpwnam(SLURM_USER).pw_uid
    slurm_group_gid = getgrnam(SLURM_GROUP).gr_gid
    return slurm_user_uid, slurm_group_gid


class SlurmctldManagerError(BaseException):
    """Exception for use with SlurmctldManager."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class CharmedHPCPackageLifecycleManager:
    """Facilitate ubuntu-hpc slurm component package lifecycles."""

    def __init__(self, package_name: str):
        self._package_name = package_name
        self._keyring_path = Path(f"/usr/share/keyrings/ubuntu-hpc-{self._package_name}.asc")

    def _repo(self) -> apt.DebianRepository:
        """Return the ubuntu-hpc repo."""
        ppa_url: str = "https://ppa.launchpadcontent.net/ubuntu-hpc/slurm-wlm-23.02/ubuntu"
        sources_list: str = (
            f"deb [signed-by={self._keyring_path}] {ppa_url} {distro.codename()} main"
        )
        return apt.DebianRepository.from_repo_line(sources_list)

    def install(self) -> bool:
        """Install package using lib apt."""
        package_installed = False

        if self._keyring_path.exists():
            self._keyring_path.unlink()
        self._keyring_path.write_text(UBUNTU_HPC_PPA_KEY)

        repositories = apt.RepositoryMapping()
        repositories.add(self._repo())

        try:
            apt.update()
            apt.add_package([self._package_name])
            package_installed = True
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found in package cache or on system.")
        except apt.PackageError as e:
            logger.error(f"Could not install '{self._package_name}'. Reason: {e.message}")

        return package_installed

    def uninstall(self) -> None:
        """Uninstall the package using libapt."""
        if apt.remove_package(self._package_name):
            logger.info(f"'{self._package_name}' removed from system.")
        else:
            logger.error(f"'{self._package_name}' not found on system.")

        repositories = apt.RepositoryMapping()
        repositories.disable(self._repo())

        if self._keyring_path.exists():
            self._keyring_path.unlink()

    def upgrade_to_latest(self) -> None:
        """Upgrade package to latest."""
        try:
            slurm_package = apt.DebianPackage.from_system(self._package_name)
            slurm_package.ensure(apt.PackageState.Latest)
            logger.info(f"Updated '{self._package_name}' to: {slurm_package.version.number}.")
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found in package cache or on system.")
        except apt.PackageError as e:
            logger.error(f"Could not install '{self._package_name}'. Reason: {e.message}")

    def version(self) -> str:
        """Return the package version."""
        slurm_package_vers = ""
        try:
            slurm_package_vers = apt.DebianPackage.from_installed_package(
                self._package_name
            ).version.number
        except apt.PackageNotFoundError:
            logger.error(f"'{self._package_name}' not found on system.")
        return slurm_package_vers


class PrometheusSlurmExporterPackageLifecycleManager(CharmedHPCPackageLifecycleManager):
    """Facilitate ubuntu-hpc prometheus-slurm-exporter package lifecycles."""

    def _repo(self) -> apt.DebianRepository:
        """Return the ubuntu-hpc repo."""
        ppa_url: str = "https://ppa.launchpadcontent.net/ubuntu-hpc/prometheus-slurm-exporter/ubuntu"
        sources_list: str = (
            f"deb [signed-by={self._keyring_path}] {ppa_url} {distro.codename()} main"
        )
        return apt.DebianRepository.from_repo_line(sources_list)


class SlurmctldManager:
    """SlurmctldManager."""

    def __init__(self, user_provided_slurm_prefix: Optional[str] = None):
        self._user_provided_slurm_prefix = user_provided_slurm_prefix

        self._path_prefix = Path(
            user_provided_slurm_prefix if user_provided_slurm_prefix is not None else "/usr"
        )

        self._bin_path = self._path_prefix / "bin"
        self._sbin_path = self._path_prefix / "sbin"
        self._plugin_dir = Path(
            f"{self._path_prefix}/lib/slurm"
            if user_provided_slurm_prefix
            else f"{self._path_prefix}/lib/x86_64-linux-gnu/slurm-wlm"
        )

        self._slurmctld_bin_path = self._sbin_path / "slurmctld"

        self._munge_bin_path = self._bin_path / "munge"
        self._unmunge_bin_path = self._bin_path / "unmunge"
        self._mungekey_bin_path = self._sbin_path / "mungekey"

        self._munge_socket_dir = Path("/var/run/munge")
        self._munge_socket_path = self._munge_socket_dir / "munge.socket.2"

    def install(self) -> bool:
        """Install slurm from user_provided or apt."""
        if self._user_provided_slurm_prefix is not None:
            Path("/etc/profile.d/Z0-slurm-user-build-path.sh").write_text(
                f'export PATH="$PATH:{self._sbin_path}:{self._bin_path}"'
            )
            self._install_user_provided_munge()
            self._install_user_provided_slurmctld()
        else:
            if self._install_from_apt() is not True:
                return False

        return True

    def install_slurm_exporter(self) -> bool:
        """Install prometheus-slurm-exporter to the system."""
        exporter_defaults_file_path = Path("/etc/default/prometheus-slurm-exporter")
        slurm_exporter = PrometheusSlurmExporterPackageLifecycleManager("prometheus-slurm-exporter")
        if slurm_exporter.install() is not False:
            systemd.service_stop("prometheus-slurm-exporter")
            slurm_exporter_options_str = (
                "-slurm.collect-diags "
                "-slurm.collect-licenses "
                "-slurm.collect-limits "
                f"-slurm.diag-cli={self._bin_path}/sdiag "
                f"-slurm.lic-cli={self._bin_path}/squeue "
                f"-slurm.squeue-cli={self._bin_path}/squeue "
                f"-slurm.sinfo-cli={self._bin_path}/sinfo "
                f"-slurm.sacctmgr-cli={self._bin_path}/sacctmgr"
            )
            exporter_defaults_file_path.write_text(
                f'ARGS="{slurm_exporter_options_str}"'
            )
            systemd.service_start("prometheus-slurm-exporter")
            return True
        return False

    def _install_from_apt(self) -> bool:
        """Install slurmctld and munge to the system."""
        slurmctld_package = CharmedHPCPackageLifecycleManager("slurmctld")
        munge_package = CharmedHPCPackageLifecycleManager("munge")

        if slurmctld_package.install() is not True:
            return False
        systemd.service_stop("slurmctld")

        if munge_package.install() is not True:
            return False
        systemd.service_stop("munge")

        spool_dir = Path("/var/spool/slurmctld")
        spool_dir.mkdir(exists_ok=True)

        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()
        os.chown(f"{spool_dir}", slurm_user_uid, slurm_group_gid)

    def _install_user_provided_slurmctld(self) -> None:
        """Provision slurmctld systemd service and dirs."""
        slurmctld_log_dir = Path("/var/log/slurm")
        slurmctld_etc_dir = Path("/etc/slurm")
        slurmctld_spool_dir = Path("/var/spool/slurmctld")
        slurmctld_defaults_file = Path("/etc/default/slurmctld")
        slurmctld_systemd_service_file = Path("/lib/systemd/system/slurmctld.service")

        slurm_user_name = "slurm"
        slurm_group_name = "slurm"
        slurm_user_uid = "64030"
        slurm_group_gid = "64030"

        self._create_user_and_group(
            slurm_user_name, slurm_group_name, slurm_user_uid, slurm_group_gid
        )

        # Create /etc/default/slurmctld
        slurmctld_options_str = (
            f"-f {slurmctld_etc_dir}/slurm.conf"
        )
        slurmctld_defaults_file.write_text(f'SLURMCTLD_OPTIONS="{slurmctld_options_str}"')



        # Create slurmctld dirs
        for slurmctld_dir in [slurmctld_log_dir, slurmctld_spool_dir, slurmctld_etc_dir]:
            slurmctld_dir.mkdir(parents=True, exist_ok=True)
            os.chown(f"{slurmctld_dir}", int(slurm_user_uid), int(slurm_group_gid))

        # Generate and write the jwt_key
        # jwt_rsa = self.generate_jwt_rsa()
        # self.write_jwt_rsa(jwt_rsa)

        # Create the systemd service file
        slurmctld_systemd_service_file.write_text(SLURMCTLD_SYSTEMD_SERVICE_FILE)
        systemd.daemon_reload()
        systemd.service_enable("slurmctld")
        # systemd.service_start("slurmctld")

    def _install_user_provided_munge(self) -> None:
        """Provision system services and dirs."""
        munge_log_dir = Path("/var/log/munge")
        munge_etc_dir = Path("/etc/munge")
        munge_seed_dir = Path("/var/lib/munge")
        munge_pid_dir = Path("/run/munge")
        munge_defaults_file = Path("/etc/default/munge")
        munge_systemd_service_file = Path("/lib/systemd/system/munge.service")

        munge_user_name = "munge"
        munge_group_name = "munge"
        munge_user_uid = "114"
        munge_group_gid = "121"

        self._create_user_and_group(
            munge_user_name, munge_group_name, munge_user_uid, munge_group_gid
        )

        # Create munge paths
        for munge_path in [munge_log_dir, munge_etc_dir, munge_seed_dir]:
            munge_path.mkdir(parents=True, exist_ok=True)
            os.chown(f"{munge_path}", int(munge_user_uid), int(munge_group_gid))

        # Create munge.key
        #munge_key = self.generate_munge_key()
        #self.write_munge_key(munge_key)

        # Create /etc/default/munge
        munge_options_str = (
            f"--log-file={munge_log_dir}/munged.log "
            f"--key-file={munge_etc_dir}/munge.key "
            f"--pid-file={munge_pid_dir}/munged.pid "
            f"--seed-file={munge_seed_dir}/munged.seed "
            f"--socket={self._munge_socket_path}"
        )
        munge_defaults_file.write_text(f'OPTIONS="{munge_options_str}"')

        # Create the systemd service file
        munge_systemd_service_file.write_text(MUNGE_SYSTEMD_SERVICE_FILE)
        systemd.daemon_reload()
        systemd.service_enable("munge")
        # systemd.service_start("munge")

    def _create_user_and_group(self, user_name: str, group_name: str, uid: str, gid: str) -> None:
        """Given a user_name, group_name, uid, and gid, create the respective group and user."""
        logger.info(f"Creating group: {group_name}")
        try:
            subprocess.check_output(["groupadd", "--gid", gid, group_name])
        except subprocess.CalledProcessError as e:
            if e.returncode == 9:
                logger.warning(f"Group, {group_name}, already exists.")
            else:
                logger.error(f"Error creating group, {group_name} : {e}")
                return False

        logger.info(f"Creating user: {user_name}")
        try:
            subprocess.check_output(
                [
                    "adduser",
                    "--system",
                    "--gid",
                    gid,
                    "--uid",
                    uid,
                    "--no-create-home",
                    "--home",
                    "/nonexistent",
                    user_name,
                ]
            )
        except subprocess.CalledProcessError as e:
            if e.returncode == 9:
                logger.warning(f"User, {user_name} already exists.")
            else:
                logger.error(f"Error creating user, {user_name}: {e}")
                return False
        logger.info(f"Created user, {user_name} with {uid} and group, {group_name} with {gid}.")

    def version(self) -> str:
        """Return slurm version."""
        slurmctld_version = ""
        if self._user_provided_slurm_prefix:
            try:
                slurmctld_version_out = subprocess.check_output([self._slurmctld_bin_path, "-V"])
            except subprocess.CalledProcessError as e:
                raise (e)
                logger.error("Error obtaining slurmctld version.")
            slurmctld_version = slurmctld_version_out.decode().strip().split()[1]
        else:
            slurmctld_version = CharmedHPCPackageLifecycleManager("slurmctld").version()
        return slurmctld_version

    def slurm_cmd(self, command, arg_string) -> None:
        """Run a slurm command."""
        try:
            subprocess.call([f"{self._bin_path}/{command}"] + arg_string.split())
        except subprocess.CalledProcessError as e:
            raise (e)
            logger.error(f"Error running {command} - {e}")

    def write_slurm_conf(self, slurm_conf: dict) -> None:
        """Render the context to a template, adding in common configs."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        target = Path("/etc/slurm/slurm.conf")
        target.write_text(slurm_conf_as_string(slurm_conf))

        os.chown(f"{target}", slurm_user_uid, slurm_group_gid)

    def write_munge_key(self, munge_key: str) -> None:
        """Base64 decode and write the munge key."""
        munge_user_uid = getpwnam("munge").pw_uid
        munge_group_gid = getgrnam("munge").gr_gid

        target = Path("/etc/munge/munge.key")
        target.write_bytes(b64decode(munge_key.encode()))

        target.chmod(0o600)
        os.chown(f"{target}", munge_user_uid, munge_group_gid)

    def write_jwt_rsa(self, jwt_rsa: str) -> None:
        """Write the jwt_rsa key."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        target = Path("/var/spool/slurmctld/jwt_hs256.key")
        target.write_text(jwt_rsa)

        target.chmod(0o600)
        os.chown(f"{target}", slurm_user_uid, slurm_group_gid)

    def write_cgroup_conf(self, cgroup_conf: str) -> None:
        """Write the cgroup.conf file."""
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()

        target = Path("/etc/slurm/cgroup.conf")
        target.write_text(cgroup_conf)

        target.chmod(0o600)
        os.chown(f"{target}", slurm_user_uid, slurm_group_gid)

    def generate_jwt_rsa(self) -> str:
        """Generate the rsa key to encode the jwt with."""
        return RSA.generate(2048).export_key("PEM").decode()

    def generate_munge_key(self) -> str:
        """Generate the munge.key."""
        munge_key_as_string = ""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_munge_key = Path(tmp_dir) / "munge.key"
            subprocess.check_call(
                [f"{self._mungekey_bin_path}", "-c", "-k", tmp_munge_key, "-b", "2048"]
            )
            munge_key_as_string = b64encode(tmp_munge_key.read_bytes()).decode()
        return munge_key_as_string

    def get_munge_key(self) -> str:
        """Read the bytes, encode to base64, decode to a string, return."""
        munge_key = Path("/etc/munge/munge.key").read_bytes()
        return b64encode(munge_key).decode()

    def stop_slurmctld(self) -> None:
        """Stop slurmctld service."""
        systemd.service_stop("slurmctld")

    def start_slurmctld(self) -> None:
        """Start slurmctld service."""
        systemd.service_start("slurmctld")

    def stop_munged(self) -> None:
        """Stop munge."""
        systemd.service_stop("munge")

    def start_munged(self) -> bool:
        """Start the munged process.

        Return True on success, and False otherwise.
        """
        logger.debug("Starting munge.")
        try:
            systemd.service_start("munge")
        # Ignore pyright error for is not a valid exception class, reportGeneralTypeIssues
        except SlurmctldManagerError(
            "Cannot start munge."
        ) as e:  # pyright: ignore [reportGeneralTypeIssues]
            logger.error(e)
            return False
        return self.check_munged()

    def check_munged(self) -> bool:
        """Check if munge is working correctly."""
        if not systemd.service_running("munge"):
            return False

        output = ""
        # check if munge is working, i.e., can use the credentials correctly
        try:
            logger.debug("## Testing if munge is working correctly")
            munge = subprocess.Popen(
                [f"{self._munge_bin_path}", f"--socket={self._munge_socket_path}", "-n"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if munge is not None:
                unmunge = subprocess.Popen(
                    [f"{self._unmunge_bin_path}", f"--socket={self._munge_socket_path}"],
                    stdin=munge.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                output = unmunge.communicate()[0].decode()
            if "Success" in output:
                logger.debug(f"## Munge working as expected: {output}")
                return True
            logger.error(f"## Munge not working: {output}")
        except subprocess.CalledProcessError as e:
            logger.error(f"## Error testing munge: {e}")

        return False

    @property
    def hostname(self) -> str:
        """Return the hostname."""
        return socket.gethostname().split(".")[0]

    @property
    def plugin_dir(self) -> str:
        """Return the plugin dir."""
        return self._plugin_dir
