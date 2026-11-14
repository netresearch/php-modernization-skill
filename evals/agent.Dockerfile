# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# Runtime for evals/run_agent_cases.py --sandbox docker: PHP, Composer, git
# and uv with Python for the skill's scripts. The claude binary is not part of the image;
# the runner mounts the host's binary read-only, so every arm runs the same
# Claude Code version as the host.
#
#   docker build -t php-modernization-evals -f evals/agent.Dockerfile evals
FROM php:8.5-cli

RUN apt-get update \
    && apt-get install -y --no-install-recommends git unzip ca-certificates ripgrep python3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV COMPOSER_NO_INTERACTION=1
