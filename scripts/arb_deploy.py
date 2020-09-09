#!/usr/bin/env python3

# Copyright 2019, Offchain Labs, Inc.
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

# ----------------------------------------------------------------------------
# arb-deploy
# ----------------------------------------------------------------------------

import argparse
import os
import sys
import json

import build_validator_docker
from support.run import run

# package configuration
NAME = "arb-deploy"
DESCRIPTION = "Manage Arbitrum dockerized deployments"

# filename constants
DOCKER_COMPOSE_FILENAME = "docker-compose.yml"

### ----------------------------------------------------------------------------
### docker-compose template
### ----------------------------------------------------------------------------

# Parameters: number of validators,
# absolute path to state folder, absolute path to contract
COMPOSE_HEADER = """# Machine generated by `arb-deploy`. Do not version control.
version: '3'
networks:
    default:
        external:
            name: arb-network
services:
    arb-tx-aggregator:
        volumes:
            - %s:/home/user/state
        image: arb-validator
        entrypoint: '/home/user/go/bin/arb-tx-aggregator'
        command: %s state %s %s
        ports:
            - '1235:1235'
            - '8547:8547'
"""


def compose_header(state_abspath, extra_flags, ws_port, rollup_address):
    return COMPOSE_HEADER % (state_abspath, extra_flags, ws_port, rollup_address)


# Parameters: validator id, absolute path to state folder,
# absolute path to contract, validator id
COMPOSE_VALIDATOR = """
    arb-validator%d:
        volumes:
            - %s:/home/user/state
        image: arb-validator
        command: validate %s state %s %s
"""


# Returns one arb-validator declaration for a docker compose file
def compose_validator(
    validator_id, state_abspath, extra_flags, ws_port, rollup_address
):
    return COMPOSE_VALIDATOR % (
        validator_id,
        state_abspath,
        extra_flags,
        ws_port,
        rollup_address,
    )


### ----------------------------------------------------------------------------
### Deploy
### ----------------------------------------------------------------------------


# Compile contracts to `contract.ao` and export to Docker and run validators
def deploy(sudo_flag, build_flag, up_flag, rollup, password):
    # Stop running Arbitrum containers
    halt_docker(sudo_flag)

    states_path = os.path.abspath(os.path.join("rollups", rollup, "validator%s"))

    n_validators = 1
    while True:
        if not os.path.exists(states_path % n_validators):
            break
        n_validators += 1

    # Overwrite DOCKER_COMPOSE_FILENAME

    compose = os.path.abspath("./" + DOCKER_COMPOSE_FILENAME)
    contents = ""
    for i in range(0, n_validators):
        with open(os.path.join(states_path % i, "config.json")) as json_file:
            data = json.load(json_file)
            rollup_address = data["rollup_address"]
            extra_flags = ""
            eth_url = (
                data["eth_url"]
                .replace("localhost", "arb-bridge-eth-geth")
                .replace("localhost", "arb-bridge-eth-geth")
            )

            if not password and "password" in data:
                extra_flags += " -password=" + data["password"]
            elif password:
                extra_flags += " -password=" + password
            else:
                raise Exception(
                    "arb_deploy requires validator password through [--password=pass] parameter or in config.json file"
                )
        if i == 0:
            contents = compose_header(
                states_path % 0, extra_flags, eth_url, rollup_address
            )
        else:
            if "blocktime" in data:
                extra_flags += " -blocktime=%s" % data["blocktime"]
            contents += compose_validator(
                i, states_path % i, extra_flags, eth_url, rollup_address
            )

    with open(compose, "w") as f:
        f.write(contents)

    # Build
    if not up_flag or build_flag:
        if build_validator_docker.build_validator(sudo_flag) != 0:
            exit(1)

    # Run
    if not build_flag or up_flag:
        print("Deploying", n_validators, "validators for rollup", rollup_address)
        run("docker-compose -f %s up" % compose, sudo=sudo_flag)


def halt_docker(sudo_flag):
    # Check for DOCKER_COMPOSE_FILENAME and halt if running
    if os.path.isfile("./" + DOCKER_COMPOSE_FILENAME):
        run(
            "docker-compose -f ./%s down -t 0" % DOCKER_COMPOSE_FILENAME,
            sudo=sudo_flag,
            capture_stdout=True,
        )

    # Kill and rm all docker containers and images created by any `arb-deploy`
    ps = "grep -e 'arb-validator' | awk '{ print $1 }'"
    if run("docker ps | " + ps, capture_stdout=True, quiet=True, sudo=sudo_flag) != "":
        run(
            "docker kill $("
            + ("sudo " if sudo_flag else "")
            + "docker ps | "
            + ps
            + ")",
            capture_stdout=True,
            sudo=sudo_flag,
        )
        run(
            "docker rm $("
            + ("sudo " if sudo_flag else "")
            + "docker ps -a | "
            + ps
            + ")",
            capture_stdout=True,
            sudo=sudo_flag,
        )


### ----------------------------------------------------------------------------
### Command line interface
### ----------------------------------------------------------------------------


def main():
    run("./scripts/create-network")

    parser = argparse.ArgumentParser(prog=NAME, description=DESCRIPTION)
    # Required
    parser.add_argument("rollup", type=str, help="The address of the rollup chain.")

    parser.add_argument("-p", "--password", help="Password protecting validator keys.")
    # Optional

    parser.add_argument(
        "-s",
        "--sudo",
        action="store_true",
        dest="sudo",
        help="Run docker-compose with sudo",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--build",
        action="store_true",
        dest="build",
        help="Run docker-compose build only",
    )
    group.add_argument(
        "--up", action="store_true", dest="up", help="Run docker-compose up only"
    )

    args = parser.parse_args()

    # Deploy
    deploy(args.sudo, args.build, args.up, args.rollup, args.password)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
