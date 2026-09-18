#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run a pull request's hosted checks locally, for review when CI did not run.

Contributor forks sometimes cannot start GitHub Actions, in which case a pull
request arrives with red checks that executed nothing. A red check that ran
nothing is not a failure and not a pass; it is an absence, and merging on it
would mean merging unverified code. This runs the same steps a maintainer's
review needs, choosing workflows with the `paths` filters the workflows
already declare, so the local set matches what the hosted set would have been.

    tools/verify-pr.py 101              # fetch the PR head and verify it
    tools/verify-pr.py 101 --keep DIR   # keep the checkout for inspection

Dependency-install steps are reported as skipped, never run: this must not
install anything. If a skipped step provided something a later step needs,
that later step fails honestly rather than appearing to pass.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WORKFLOWS = ROOT / '.github/workflows'
REPO = 'iconidentify/omarchy-m1-video'
INSTALLERS = ('apt-get', 'sudo ', 'pip install')


def gh(*args):
    out = subprocess.run(['gh', *args], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f'gh {" ".join(args)} failed:\n{out.stderr.strip()}')
    return out.stdout


def load_workflows():
    try:
        import yaml
    except ImportError:
        raise SystemExit('PyYAML is required: pip install --user PyYAML')
    flows = {}
    for path in sorted(WORKFLOWS.glob('*.yml')):
        doc = yaml.safe_load(path.read_text())
        # YAML 1.1 reads a bare `on:` key as True.
        triggers = doc.get('on', doc.get(True)) or {}
        paths = (triggers.get('pull_request') or {}).get('paths')
        steps = []
        for job in (doc.get('jobs') or {}).values():
            for step in job.get('steps') or []:
                if 'run' in step:
                    steps.append((step.get('name') or step['run'].strip().splitlines()[0],
                                  step['run']))
        flows[path.name] = {'paths': paths, 'steps': steps,
                            'name': doc.get('name', path.stem)}
    return flows


def matches(pattern, path):
    if pattern.endswith('/**'):
        return path.startswith(pattern[:-2])
    return fnmatch.fnmatch(path, pattern)


def selected(flows, changed):
    hit = {}
    for filename, flow in flows.items():
        if flow['paths'] is None:                      # unfiltered: always runs
            hit[filename] = flow
        elif any(matches(p, f) for p in flow['paths'] for f in changed):
            hit[filename] = flow
    return hit


MISSING = ('ModuleNotFoundError', 'command not found', 'No such file or directory',
           'Package .* was not found', 'not found in PKG_CONFIG_PATH')


def run_steps(flow, tree, env):
    results, skipped_install = [], False
    for name, script in flow['steps']:
        if any(token in script for token in INSTALLERS):
            skipped_install = True
            results.append((name, 'SKIPPED', 'installs dependencies; not run locally'))
            continue
        proc = subprocess.run(['bash', '-euo', 'pipefail', '-c', script],
                              cwd=tree, env=env, capture_output=True, text=True)
        output = proc.stdout + proc.stderr
        if proc.returncode == 0:
            results.append((name, 'PASS', ''))
            continue
        tail = '\n'.join('      ' + t for t in output.strip().splitlines()[-25:])
        # A step that fails only because a skipped install never provided its
        # dependency says nothing about the change. Report it as unverified
        # rather than as a defect, and never as a pass.
        unverified = skipped_install and any(m in output for m in MISSING)
        results.append((name, 'UNVERIFIED' if unverified else 'FAIL', tail))
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('pr', type=int, help='pull request number')
    ap.add_argument('--keep', type=Path, help='keep the checkout in this directory')
    ap.add_argument('--list', action='store_true',
                    help='show which workflows and steps would run, without running them')
    ap.add_argument('--repo', default=REPO)
    args = ap.parse_args()

    meta = json.loads(gh('pr', 'view', str(args.pr), '--repo', args.repo,
                         '--json', 'headRefOid,files,title,state'))
    head = meta['headRefOid']
    changed = [f['path'] for f in meta['files']]
    print(f'PR #{args.pr} [{meta["state"]}] {meta["title"]}')
    print(f'head {head}   {len(changed)} changed files\n')

    flows = load_workflows()
    chosen = selected(flows, changed)
    if not chosen:
        print('No workflow matches these paths; nothing to verify locally.')
        return 0
    print('Workflows this change would run:')
    for filename, flow in sorted(chosen.items()):
        print(f'  {flow["name"]}  ({filename})')
        if args.list:
            for name, script in flow['steps']:
                mark = 'skip' if any(t in script for t in INSTALLERS) else 'run '
                print(f'      {mark}  {name[:76]}')
    print()
    if args.list:
        print(f'{len(chosen)} of {len(flows)} workflows selected; nothing was run.')
        return 0

    temp = tempfile.mkdtemp(prefix='verify-pr-')
    tree = Path(args.keep) if args.keep else Path(temp) / 'tree'
    tree.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'fetch', '--quiet', 'origin', f'pull/{args.pr}/head'],
                   cwd=ROOT, check=True)
    subprocess.run(['git', 'worktree', 'add', '--quiet', '--detach', str(tree), head],
                   cwd=ROOT, check=True)

    env = os.environ | {'RUNNER_TEMP': temp, 'CI': 'true'}
    failures = skipped = unverified = 0
    try:
        for filename, flow in sorted(chosen.items()):
            print(f'=== {flow["name"]} ===')
            for name, status, detail in run_steps(flow, tree, env):
                print(f'  {status:10} {name[:80]}')
                if detail and status == 'FAIL':
                    print(detail)
                failures += status == 'FAIL'
                skipped += status == 'SKIPPED'
                unverified += status == 'UNVERIFIED'
            print()
    finally:
        if not args.keep:
            subprocess.run(['git', 'worktree', 'remove', '--force', str(tree)],
                           cwd=ROOT, check=False)
            shutil.rmtree(temp, ignore_errors=True)
        else:
            print(f'checkout kept at {tree}; remove with '
                  f'`git worktree remove --force {tree}`')

    print(f'{failures} failing, {unverified} unverified, '
          f'{skipped} skipped (dependency installs).')
    if unverified:
        print('Unverified steps needed a dependency this host does not have. They '
              'are not failures of the change, and they are not passes: install '
              'the dependency and rerun, or verify them another way before merging.')
    if failures:
        print('Failing steps are real: the change does not pass its own checks.')
    if not failures and not unverified:
        print('Every check this change would run on hosted CI passed here.')
    return 1 if (failures or unverified) else 0


if __name__ == '__main__':
    sys.exit(main())
