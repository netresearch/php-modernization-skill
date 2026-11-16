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
FROM php:8.5-cli@sha256:50956f094e90a716d43bea28087d447555ad80510e386ab8c9c10d8c70d781a9

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git python3 ripgrep tinyproxy unzip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=composer:2@sha256:0c8e663f14c94d07b3c45b175c51f5a14718508f21fe4dd7e54f09488dd0ed71 /usr/bin/composer /usr/local/bin/composer
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 /uv /uvx /usr/local/bin/

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

# The runner passes --user with the host's uid for agents and the checker;
# this default covers the proxy and any container started without it.
RUN useradd --uid 10001 --create-home eval
USER eval
