# Copyright (c) 2025 Omnivector, LLC

"""Slurmd Charm Constants."""

CHARM_MAINTAINED_NHC_CONFIG = """
# Enforce short hostnames to match the node names as tracked by slurm.
* || HOSTNAME="$HOSTNAME_S"

"""
