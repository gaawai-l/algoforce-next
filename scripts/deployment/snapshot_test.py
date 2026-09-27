"""Create a test deployment commit without changing the active branch or staging area."""
import json
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'.local/test-deploy'


def run(*args: str, **kwargs: object) -> str:
    return subprocess.check_output(list(args),cwd=ROOT,text=True,**kwargs).strip()


def main() -> None:
    base=run('git','rev-parse','origin/main')
    index=STATE/'deployment-index'
    env={**os.environ,'GIT_INDEX_FILE':str(index)}
    run('git','read-tree',base,env=env)
    included=[]
    for directory in ('deploy/test','services/analytics/src','services/analytics/tests',
                      'integrations/wealthfolio/overlay'):
        for path in sorted((ROOT/directory).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and not any(part.endswith('.egg-info') for part in path.parts) and path.suffix not in {'.pyc','.sqlite','.db'}:
                included.append(path.relative_to(ROOT).as_posix())
    included += ['.dockerignore','services/analytics/pyproject.toml',
                 'services/analytics/requirements.lock','integrations/wealthfolio/openapi.json',
                 'integrations/wealthfolio/upstream.json',
                 'integrations/wealthfolio/patches/0001-python-host-extension.patch',
                 'scripts/deployment/snapshot_test.py']
    run('git','add','--',*included,env=env)
    tree=run('git','write-tree',env=env)
    commit=run('git','commit-tree',tree,'-p',base,'-m','Package isolated Wheelhouse test deployment')
    branch='codex/test-environment'
    if subprocess.run(['git','show-ref','--verify','--quiet',f'refs/heads/{branch}'],cwd=ROOT).returncode==0:
        raise SystemExit('Deployment branch exists; create a reviewed follow-up commit instead')
    run('git','update-ref',f'refs/heads/{branch}',commit)
    (STATE/'snapshot.json').write_text(json.dumps({'base':base,'commit':commit,'branch':branch,'included':included},indent=2)+'\n')
    print(f'Created {branch} at {commit}; active checkout unchanged.')


if __name__=='__main__':main()
