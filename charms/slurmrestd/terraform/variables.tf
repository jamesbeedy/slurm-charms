# Copyright 2024 Canonical Ltd.
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

variable "app_name" {
  description = "Name of the slurmrestd application within the Juju model"
  type        = string
}

variable "channel" {
  description = "Channel to deploy the slurmrestd charm from."
  type        = string
  default     = "latest/stable"
}

variable "config" {
  description = "Initial configuration for deployed slurmrestd charm."
  type        = map(string)
  default     = {}
}

variable "model_name" {
  description = "Name of model to deploy slurmrestd charm to."
  type        = string
}

variable "revision" {
  description = "Revision of the slurmrestd charm to deploy."
  type        = number
  default     = null
}

variable "units" {
  description = "Number of slurmrestd units to deploy."
  type        = number
  default     = 1
}