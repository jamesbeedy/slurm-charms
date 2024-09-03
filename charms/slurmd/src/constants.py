# Copyright 2024 Omnivector, LLC.
# See LICENSE file for licensing details.
"""constants for slurmd-operator charm."""
from pathlib import Path

SLURMD_USER_NAME = "root"
SLURMD_GROUP_NAME = "root"

SLURM_USER_NAME = "slurm"
SLURM_GROUP_NAME = "slurm"
SLURM_USER_UID = "64030"
SLURM_GROUP_GID = "64030"

MUNGE_USER_NAME = "munge"
MUNGE_GROUP_NAME = "munge"
MUNGE_USER_UID = "114"
MUNGE_GROUP_GID = "121"

MUNGE_KEY_PATH = Path("/etc/munge/munge.key")

UBUNTU_HPC_PPA_KEY = """
-----BEGIN PGP PUBLIC KEY BLOCK-----
Comment: Hostname:
Version: Hockeypuck 2.1.1-10-gec3b0e7

xsFNBGTuZb8BEACtJ1CnZe6/hv84DceHv+a54y3Pqq0gqED0xhTKnbj/E2ByJpmT
NlDNkpeITwPAAN1e3824Me76Qn31RkogTMoPJ2o2XfG253RXd67MPxYhfKTJcnM3
CEkmeI4u2Lynh3O6RQ08nAFS2AGTeFVFH2GPNWrfOsGZW03Jas85TZ0k7LXVHiBs
W6qonbsFJhshvwC3SryG4XYT+z/+35x5fus4rPtMrrEOD65hij7EtQNaE8owuAju
Kcd0m2b+crMXNcllWFWmYMV0VjksQvYD7jwGrWeKs+EeHgU8ZuqaIP4pYHvoQjag
umqnH9Qsaq5NAXiuAIAGDIIV4RdAfQIR4opGaVgIFJdvoSwYe3oh2JlrLPBlyxyY
dayDifd3X8jxq6/oAuyH1h5K/QLs46jLSR8fUbG98SCHlRmvozTuWGk+e07ALtGe
sGv78ToHKwoM2buXaTTHMwYwu7Rx8LZ4bZPHdersN1VW/m9yn1n5hMzwbFKy2s6/
D4Q2ZBsqlN+5aW2q0IUmO+m0GhcdaDv8U7RVto1cWWPr50HhiCi7Yvei1qZiD9jq
57oYZVqTUNCTPxi6NeTOdEc+YqNynWNArx4PHh38LT0bqKtlZCGHNfoAJLPVYhbB
b2AHj9edYtHU9AAFSIy+HstET6P0UDxy02IeyE2yxoUBqdlXyv6FL44E+wARAQAB
zRxMYXVuY2hwYWQgUFBBIGZvciBVYnVudHUgSFBDwsGOBBMBCgA4FiEErocSHcPk
oLD4H/Aj9tDF1ca+s3sFAmTuZb8CGwMFCwkIBwIGFQoJCAsCBBYCAwECHgECF4AA
CgkQ9tDF1ca+s3sz3w//RNawsgydrutcbKf0yphDhzWS53wgfrs2KF1KgB0u/H+u
6Kn2C6jrVM0vuY4NKpbEPCduOj21pTCepL6PoCLv++tICOLVok5wY7Zn3WQFq0js
Iy1wO5t3kA1cTD/05v/qQVBGZ2j4DsJo33iMcQS5AjHvSr0nu7XSvDDEE3cQE55D
87vL7lgGjuTOikPh5FpCoS1gpemBfwm2Lbm4P8vGOA4/witRjGgfC1fv1idUnZLM
TbGrDlhVie8pX2kgB6yTYbJ3P3kpC1ZPpXSRWO/cQ8xoYpLBTXOOtqwZZUnxyzHh
gM+hv42vPTOnCo+apD97/VArsp59pDqEVoAtMTk72fdBqR+BB77g2hBkKESgQIEq
EiE1/TOISioMkE0AuUdaJ2ebyQXugSHHuBaqbEC47v8t5DVN5Qr9OriuzCuSDNFn
6SBHpahN9ZNi9w0A/Yh1+lFfpkVw2t04Q2LNuupqOpW+h3/62AeUqjUIAIrmfeML
IDRE2VdquYdIXKuhNvfpJYGdyvx/wAbiAeBWg0uPSepwTfTG59VPQmj0FtalkMnN
ya2212K5q68O5eXOfCnGeMvqIXxqzpdukxSZnLkgk40uFJnJVESd/CxHquqHPUDE
fy6i2AnB3kUI27D4HY2YSlXLSRbjiSxTfVwNCzDsIh7Czefsm6ITK2+cVWs0hNQ=
=cs1s
-----END PGP PUBLIC KEY BLOCK-----
"""

MUNGE_SYSTEMD_SERVICE_FILE = """
[Unit]
Description=MUNGE authentication service
Documentation=man:munged(8)
After=network.target
After=time-sync.target

[Service]
Type=forking
EnvironmentFile=-/etc/default/munge
ExecStart=/srv/slurm/view/sbin/munged $OPTIONS
PIDFile=/run/munge/munged.pid
RuntimeDirectory=munge
RuntimeDirectoryMode=0755
User=munge
Group=munge
Restart=on-abort

[Install]
WantedBy=multi-user.target
"""

SLURMD_SYSTEMD_SERVICE_FILE = """
[Unit]
Description=Slurm node daemon
After=munge.service network-online.target remote-fs.target sssd.service
Wants=network-online.target

[Service]
Type=notify
EnvironmentFile=-/etc/default/slurmd
RuntimeDirectory=slurm
RuntimeDirectoryMode=0755
ExecStart=/srv/slurm/view/sbin/slurmd --systemd $SLURMD_OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process
LimitNOFILE=131072
LimitMEMLOCK=infinity
LimitSTACK=infinity
Delegate=yes

# Uncomment the following lines to disable logging through journald.
# NOTE: It may be preferable to set these through an override file instead.
#StandardOutput=null
#StandardError=null

[Install]
WantedBy=multi-user.target
"""
