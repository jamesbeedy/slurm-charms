# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""SlurmManager."""

import logging
import os
import shlex
import subprocess
import textwrap
from base64 import b64decode
from grp import getgrnam
from pathlib import Path
from pwd import getpwnam
from shutil import rmtree
from typing import Any, Dict, Optional

import distro
from constants import (
    MUNGE_KEY_PATH,
    MUNGE_SYSTEMD_SERVICE_FILE,
    SLURM_GROUP_NAME,
    SLURM_USER_NAME,
    SLURM_GROUP_GID,
    SLURM_USER_UID,
    SLURMD_GROUP_NAME,
    SLURMD_USER_NAME,
    MUNGE_USER_NAME,
    MUNGE_GROUP_NAME,
    MUNGE_USER_UID,
    MUNGE_GROUP_GID,
    SLURMD_SYSTEMD_SERVICE_FILE,
    UBUNTU_HPC_PPA_KEY
)

import charms.operator_libs_linux.v0.apt as apt  # type: ignore [import-untyped]
import charms.operator_libs_linux.v1.systemd as systemd  # type: ignore [import-untyped]

logger = logging.getLogger()


TEMPLATE_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "templates"


def _get_slurm_user_uid_and_slurm_group_gid():
    """Return the slurm user uid and slurm group gid."""
    slurm_user_uid = getpwnam(SLURMD_USER_NAME).pw_uid
    slurm_group_gid = getgrnam(SLURMD_GROUP_NAME).gr_gid
    return slurm_user_uid, slurm_group_gid


class SlurmdException(BaseException):
    """SlurmdException."""

    def __init__(self, msg):
        pass


class CharmedHPCPackageLifecycleManager:
    """Facilitate ubuntu-hpc slurm component package lifecycles."""

    def __init__(self, package_name: str):
        self._package_name = package_name
        self._keyring_path = Path(f"/usr/share/keyrings/ubuntu-hpc-{self._package_name}.asc")

    def _repo(self) -> apt.DebianRepository:
        """Return the ubuntu-hpc repo."""
        ppa_url = "https://ppa.launchpadcontent.net/ubuntu-hpc/slurm-wlm-23.02/ubuntu"
        sources_list = f"deb [signed-by={self._keyring_path}] {ppa_url} {distro.codename()} main"
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


class SlurmdManager:
    """SlurmdManager."""

    def __init__(self, user_provided_slurm_prefix: Optional[str] = None):
        self._user_provided_slurm_prefix = user_provided_slurm_prefix

        self._path_prefix = Path(
            user_provided_slurm_prefix if user_provided_slurm_prefix is not None else "/usr"
        )

        self._bin_path = self._path_prefix / "bin"
        self._sbin_path = self._path_prefix / "sbin"

        self._slurmd_bin_path = self._sbin_path / "slurmd"

        self._munge_bin_path = self._bin_path / "munge"
        self._unmunge_bin_path = self._bin_path / "unmunge"

        self._munge_socket_dir = Path("/var/run/munge")
        self._munge_socket_path = self._munge_socket_dir / "munge.socket.2"

    def install(self) -> bool:
        """Install slurm from user_provided or apt."""
        if self._user_provided_slurm_prefix is not None:
            Path("/etc/profile.d/Z0-slurm-user-build-path.sh").write_text(
                f'export PATH="$PATH:{self._sbin_path}:{self._bin_path}"'
            )
            self._install_user_provided_munge()
            self._install_user_provided_slurmd()
        else:
            if self._install_from_apt() is not True:
                return False

        return True

    def install_from_apt(self) -> bool:
        """Install slurmd, slurm-client and munge packages to the system."""
        self._munge_package = CharmedHPCPackageLifecycleManager("munge")
        self._slurmd_package = CharmedHPCPackageLifecycleManager("slurmd")
        self._slurm_client_package = CharmedHPCPackageLifecycleManager("slurm-client")

        if self._slurmd_package.install() is not True:
            logger.debug("Cannot install 'slurmd' package.")
            return False

        systemd.service_stop("slurmd")

        if self._munge_package.install() is not True:
            logger.debug("Cannot install 'munge' package.")
            return False

        systemd.service_stop("munge")

        if self._slurm_client_package.install() is not True:
            logger.debug("Cannot install 'slurm-client' package.")
            return False

        if not self._install_nhc_from_tarball():
            logger.debug("Cannot install NHC")
            return False

        self.render_nhc_config()

        spool_dir = Path("/var/spool/slurmd")
        spool_dir.mkdir()

        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()
        os.chown(f"{spool_dir}", slurm_user_uid, slurm_group_gid)

        return True

    def override_default(self, host: str) -> None:
        Path("/etc/default/slurmd").write_text(
            textwrap.dedent(
                f"""
                SLURMD_OPTIONS="--conf-server {host}:6817 -d {self._sbin_path}/slurmstepd"
                """
            ).strip()
        )

    def _install_user_provided_slurmd(self) -> None:
        """Provision slurmd systemd service and dirs."""
        slurmd_log_dir = Path("/var/log/slurm")
        slurmd_etc_dir = Path("/etc/slurm")
        slurmd_spool_dir = Path("/var/spool/slurmd")
        slurmd_systemd_service_file = Path("/lib/systemd/system/slurmd.service")

        self._create_user_and_group(
            SLURM_USER_NAME,SLURM_GROUP_NAME, SLURM_USER_UID, SLURM_GROUP_GID
        )

        # Create slurmd dirs
        slurm_user_uid, slurm_group_gid = _get_slurm_user_uid_and_slurm_group_gid()
        for slurmd_dir in [slurmd_log_dir, slurmd_spool_dir, slurmd_etc_dir]:
            slurmd_dir.mkdir(parents=True, exist_ok=True)
            os.chown(f"{slurmd_dir}", int(slurm_user_uid), int(slurm_group_gid))

        # Generate and write the jwt_key
        # jwt_rsa = self.generate_jwt_rsa()
        # self.write_jwt_rsa(jwt_rsa)

        # Create the systemd service file
        slurmd_systemd_service_file.write_text(SLURMD_SYSTEMD_SERVICE_FILE)
        systemd.daemon_reload()
        systemd.service_enable("slurmd")
        # systemd.service_start("slurmctld")

    def _install_user_provided_munge(self) -> None:
        """Provision system services and dirs."""
        munge_log_dir = Path("/var/log/munge")
        munge_etc_dir = Path("/etc/munge")
        munge_seed_dir = Path("/var/lib/munge")
        munge_pid_dir = Path("/run/munge")
        munge_defaults_file = Path("/etc/default/munge")
        munge_systemd_service_file = Path("/lib/systemd/system/munge.service")

        self._create_user_and_group(
            MUNGE_USER_NAME, MUNGE_GROUP_NAME, MUNGE_USER_UID, MUNGE_GROUP_GID
        )

        # Create munge paths
        for munge_path in [munge_log_dir, munge_etc_dir, munge_seed_dir]:
            munge_path.mkdir(parents=True, exist_ok=True)
            os.chown(f"{munge_path}", int(MUNGE_USER_UID), int(MUNGE_GROUP_GID))

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

    def stop(self) -> None:
        """Start slurmd service."""
        systemd.service_start("slurmd")

    def stop(self) -> None:
        """Stop slurmd service."""
        systemd.service_stop("slurmd")

    def restart(self) -> None:
        """Restart slurmd service."""
        systemd.service_restart("slurmd")

    def version(self) -> str:
        """Return slurmd version."""
        slurmd_version = ""
        if self._user_provided_slurm_prefix:
            try:
                slurmd_version_out = subprocess.check_output([self._slurmd_bin_path, "-V"])
            except subprocess.CalledProcessError as e:
                raise (e)
                logger.error("Error obtaining slurmd version.")
            slurmd_version = slurmd_version_out.decode().strip().split()[1]
        else:
            slurmd_version = CharmedHPCPackageLifecycleManager("slurmd").version()
        return slurmd_version

    def write_munge_key(self, munge_key: str) -> None:
        """Base64 decode and write the munge key."""
        key = b64decode(munge_key.encode())
        MUNGE_KEY_PATH.write_bytes(key)
        os.chown(f"{MUNGE_KEY_PATH}", int(MUNGE_USER_UID), int(MUNGE_GROUP_GID))
        MUNGE_KEY_PATH.chmod(0o400)  # everybody can read/execute, owner can write

    def _install_nhc_from_tarball(self) -> bool:
        """Install NHC from tarball that is packaged with the charm.

        Returns True on success, False otherwise.
        """
        logger.info("#### Installing NHC")

        base_path = Path("/tmp/nhc")

        if base_path.exists():
            rmtree(base_path)
        base_path.mkdir()

        cmd = f"tar --extract --directory {base_path} --file lbnl-nhc-1.4.3.tar.gz".split()
        try:
            result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            logger.debug(result)
        except subprocess.CalledProcessError as e:
            logger.error("failed to extract NHC using tar. reason:\n%s", e.stdout)
            return False

        full_path = base_path / os.listdir(base_path)[0]

        libdir = "/usr/lib"
        # NOTE: this requires make. We install it using the dispatch file in
        # the slurmd charm.
        try:
            locale = {"LC_ALL": "C", "LANG": "C.UTF-8"}
            cmd = f"./autogen.sh --prefix=/usr --sysconfdir=/etc \
                                 --libexecdir={libdir}".split()
            logger.info("##### NHC - running autogen")
            r = subprocess.run(
                cmd, cwd=full_path, env=locale, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            logger.debug(f"##### autogen: {r.stdout.decode()}")
            r.check_returncode()

            logger.info("##### NHC - running tests")
            r = subprocess.run(
                ["make", "test"],
                cwd=full_path,
                env=locale,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logger.debug(f"##### NHC make test: {r.stdout.decode()}")
            r.check_returncode()
            if "tests passed" not in r.stdout.decode():
                logger.error("##### NHC tests failed")
                logger.error("##### Error installing NHC")
                return False

            logger.info("##### NHC - installing")
            r = subprocess.run(
                ["make", "install"],
                cwd=full_path,
                env=locale,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            logger.debug(f"##### NHC make install: {r.stdout.decode()}")
            r.check_returncode()
        except subprocess.CalledProcessError as e:
            logger.error(f"#### Error installing NHC: {e.cmd}")
            return False

        rmtree(base_path)
        logger.info("#### NHC successfully installed")
        return True

    def render_nhc_config(self, extra_configs=None) -> bool:
        """Render basic NHC.conf during installation.

        Returns True on success, False otherwise.
        """
        target = Path("/etc/nhc/nhc.conf")
        template = TEMPLATE_DIR / "nhc.conf.tmpl"

        try:
            target.write_text(template.read_text())
        except FileNotFoundError as e:
            logger.error(f"#### Error rendering NHC.conf: {e}")
            return False

        return True

    def render_nhc_wrapper(self, params: str) -> None:
        """Render the /usr/sbin/omni-nhc-wrapper script."""
        logger.debug(f"## rendering /usr/sbin/omni-nhc-wrapper: {params}")

        target = Path("/usr/sbin/omni-nhc-wrapper")

        target.write_text(
            textwrap.dedent(
                f"""
                #!/usr/bin/env bash

                /usr/sbin/nhc-wrapper {params}
                """
            ).strip()
        )
        target.chmod(0o755)  # everybody can read/execute, owner can write

    def get_nhc_config(self) -> str:
        """Get current nhc.conf."""
        target = Path("/etc/nhc/nhc.conf")
        if target.exists():
            return target.read_text()
        return f"{target} not found."

    def restart_munged(self) -> bool:
        """Restart the munged process.

        Return True on success, and False otherwise.
        """
        try:
            logger.debug("## Restarting munge")
            systemd.service_restart("munge")
        except SlurmdException("Cannot start munge.") as e:  # type: ignore [misc]
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

    def get_node_config(self) -> Dict[Any, Any]:
        """Return the node configuration options as reported by slurmd -C."""
        slurmd_config_options = ""
        try:
            slurmd_config_options = subprocess.check_output([f"{self._slurmd_bin_path}", "-C"], text=True).strip()
        except subprocess.CalledProcessError as e:
            logger.error(e)
            raise e

        slurmd_config_options_parsed = {str(): str()}
        try:
            slurmd_config_options_parsed = {
                item.split("=")[0]: item.split("=")[1]
                for item in slurmd_config_options.split()
                if item.split("=")[0] != "UpTime"
            }
        except IndexError as e:
            logger.error("Trouble accessing elements of the list.")
            raise e

        return slurmd_config_options_parsed
