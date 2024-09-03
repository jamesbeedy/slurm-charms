#!/bin/env bash


slurm_build_dir="/srv/slurm"

#sudo mkdir -p $slurm_build_dir
#sudo chown -R $(echo $USER):$(echo $USER) $slurm_build_dir

#spack env activate .
#spack concretize
#cp slurm.patch ./.spack-env/repos/builtin/packages/slurm/
#cp package.py ./.spack-env/repos/builtin/packages/slurm/
#spack install -j$(nproc)


juju_model_name="slurm-user-build"

juju add-model $juju_model_name

cat << EOY | lxc profile edit juju-$juju_model_name
name: juju-$juju_model_name
description: Juju LXD profile

config:
  boot.autostart: "true"
  security.nesting: "true"

devices:
  slurm:
    path: /srv/slurm
    source: /srv/slurm
    type: disk
EOY

juju deploy ./slurm-charm-bundle.yaml
