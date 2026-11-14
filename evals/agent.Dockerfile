# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Netresearch DTT GmbH
#
# Runtime for evals/run_agent_cases.py --sandbox docker: PHP, Composer, git
# and uv with Python for the skill's scripts and the checker. The claude
# binary is not part of the image; the runner mounts the host's binary
# read-only, so every arm runs the same Claude Code version as the host.
#
# The same image runs the egress proxy (tinyproxy): agents sit on an internal
# network whose only way out is that proxy, and it lets through the hosts in
# /etc/tinyproxy/allow only.
#
#   docker build -t php-modernization-evals -f evals/agent.Dockerfile evals
FROM php:8.5-cli

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git unzip ca-certificates ripgrep python3 tinyproxy \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/composer
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN printf '%s\n' '^api\.anthropic\.com$' > /etc/tinyproxy/allow \
    && printf '%s\n' \
        'Port 8888' \
        'Listen 0.0.0.0' \
        'Timeout 1800' \
        'MaxClients 50' \
        'LogLevel Connect' \
        'Filter "/etc/tinyproxy/allow"' \
        'FilterType ere' \
        'FilterURLs Off' \
        'FilterDefaultDeny Yes' \
        'ConnectPort 443' \
        > /etc/tinyproxy/eval.conf

ENV COMPOSER_NO_INTERACTION=1
