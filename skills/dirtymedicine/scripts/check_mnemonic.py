"""Check candidate mapping completeness before an independent editorial review.

Usage: python check_mnemonic.py candidate.json --targets G6PD 'Heinz bodies' 'bite cells'
This checks explicit data and does not measure human recall or humor.
"""
import argparse
import json
from pathlib import Path


def validate(candidate, targets):
    errors = []
    mapped = {row['entity'] for row in candidate.get('mapping', [])}
    missing = set(targets) - mapped
    if missing:
        errors.append('Missing target mappings: ' + ', '.join(sorted(missing)))
    for row in candidate.get('mapping', []):
        if not row.get('cue') or not row.get('entity'):
            errors.append('Empty cue or entity in mapping')
    if not candidate.get('scene') or not candidate.get('spoken_take'):
        errors.append('Missing scene or speakable teaching take')
    return {'structural_checks_passed': not errors, 'errors': errors,
            'editorial_review_required': True, 'human_recall_test_performed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--targets', nargs='+', required=True)
    args = parser.parse_args()
    result = validate(json.loads(args.candidate.read_text()), args.targets)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['structural_checks_passed'] else 1)
