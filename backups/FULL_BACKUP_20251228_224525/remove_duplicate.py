#!/usr/bin/env python3
"""Remove duplicate _extract_from_wikipedia method and update it"""

with open('c:/ATS/app/services/company_extraction_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find both occurrences of def _extract_from_wikipedia
occurrences = []
for i, line in enumerate(lines):
    if 'def _extract_from_wikipedia' in line:
        occurrences.append(i)

print(f"Found _extract_from_wikipedia at lines: {[i+1 for i in occurrences]}")

if len(occurrences) == 2:
    # Find the end of the second occurrence (look for next def or end of class)
    second_start = occurrences[1]
    second_end = None
    
    for i in range(second_start + 1, len(lines)):
        if lines[i].strip().startswith('def ') and not lines[i].strip().startswith('def _extract_from_wikipedia'):
            second_end = i
            break
    
    if second_end:
        print(f"Second occurrence: lines {second_start+1} to {second_end}")
        print("Removing duplicate...")
        
        # Remove the duplicate
        new_lines = lines[:second_start] + lines[second_end:]
        
        with open('c:/ATS/app/services/company_extraction_service.py', 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        
        print(f"✅ Removed duplicate. File now has {len(new_lines)} lines (was {len(lines)})")
    else:
        print("Could not find end of second occurrence")
else:
    print(f"Expected 2 occurrences, found {len(occurrences)}")
