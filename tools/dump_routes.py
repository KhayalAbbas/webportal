#!/usr/bin/env python3
"""Dump all FastAPI routes for debugging."""

import os
import sys

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

def dump_routes():
    print("FastAPI Routes:")
    print("=" * 50)
    for route in app.routes:
        if hasattr(route, 'methods') and hasattr(route, 'path'):
            methods = ', '.join(sorted(route.methods))
            print(f"{methods:10} {route.path}")
        elif hasattr(route, 'path'):
            print(f"{'*':10} {route.path}")
    print("=" * 50)

if __name__ == "__main__":
    dump_routes()