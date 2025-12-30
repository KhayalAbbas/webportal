#!/usr/bin/env python3

import json

with open('openapi_discovery.json', 'r') as f:
    data = json.load(f)

print('=== KEY PROSPECT READ ENDPOINTS ===')
for path in ['/company-research/prospects/{prospect_id}', '/company-research/prospects/{prospect_id}/evidence', '/company-research/runs/{run_id}/prospects']:
    if path in data['paths']:
        for method, details in data['paths'][path].items():
            print(f'{method.upper()} {path}:')
            summary = details.get('summary', 'N/A')
            print(f'  Summary: {summary}')
            if '200' in details.get('responses', {}):
                schema = details['responses']['200'].get('content', {}).get('application/json', {}).get('schema', {})
                if 'properties' in schema:
                    print(f'  Returns: {list(schema["properties"].keys())}')
                elif '$ref' in schema:
                    print(f'  Returns: {schema["$ref"]}')
            print()

print('=== ROUTER MODULE MAPPING ===')
# Find which modules implement these routes by examining operation IDs
for path in data['paths'].keys():
    if any(term in path.lower() for term in ['research', 'prospect', 'evidence', 'source']):
        for method, details in data['paths'][path].items():
            operation_id = details.get('operationId', 'N/A')
            if operation_id != 'N/A':
                # Extract module from operation ID pattern
                if '_' in operation_id:
                    parts = operation_id.split('_')
                    module_hint = '_'.join(parts[:-2])  # Remove last two parts (usually method_path)
                    print(f'{path} ({method.upper()}): {operation_id} -> likely from {module_hint}')