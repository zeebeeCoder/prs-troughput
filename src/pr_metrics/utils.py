#!/usr/bin/env python3
"""Utility functions."""

import os


def resolve_org(args_org=None):
    """Resolve organization from multiple sources with priority"""
    # Priority: CLI arg > env var > hardcoded default
    if args_org:
        return args_org

    env_org = os.getenv('PR_METRICS_ORG')
    if env_org:
        return env_org

    # Default fallback
    return "Eve-World-Platform"


def sanitize_org_name(org_name):
    """Sanitize org name for safe filesystem usage"""
    return org_name.lower().replace(' ', '-').replace('_', '-')
