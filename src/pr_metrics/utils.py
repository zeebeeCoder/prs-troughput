#!/usr/bin/env python3
"""Utility functions."""

import os


def resolve_org(args_org=None):
    """Resolve organization from multiple sources with priority"""
    # Priority: CLI arg > env var
    if args_org:
        return args_org

    env_org = os.getenv('PR_METRICS_ORG')
    if env_org:
        return env_org

    # No default - require explicit org specification
    raise ValueError(
        "GitHub organization not specified. Please provide it via:\n"
        "  1. CLI flag: --org 'YourOrg'\n"
        "  2. Environment variable: export PR_METRICS_ORG='YourOrg'"
    )


def sanitize_org_name(org_name):
    """Sanitize org name for safe filesystem usage"""
    return org_name.lower().replace(' ', '-').replace('_', '-')
