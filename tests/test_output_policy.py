from types import SimpleNamespace
from simplecae import output_policy


def test_ignored_output_does_not_suppress_later_unignored_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(output_policy, '_reported', set())
    outcomes = iter([0, 1])
    def run(args, **kwargs):
        if 'rev-parse' in args:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path))
        return SimpleNamespace(returncode=next(outcomes))
    monkeypatch.setattr(output_policy.subprocess, 'run', run)
    assert output_policy.output_warning(tmp_path/'out/cae/run') is None
    assert 'not ignored' in output_policy.output_warning(tmp_path/'results/run')
    assert output_policy.output_warning(tmp_path/'results/other') is None


def test_git_probe_error_does_not_disable_later_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(output_policy, '_reported', set())
    outcomes = iter([128, 1])
    def run(args, **kwargs):
        if 'rev-parse' in args:
            return SimpleNamespace(returncode=0, stdout=str(tmp_path))
        return SimpleNamespace(returncode=next(outcomes))
    monkeypatch.setattr(output_policy.subprocess, 'run', run)
    assert output_policy.output_warning(tmp_path/'first') is None
    assert 'not ignored' in output_policy.output_warning(tmp_path/'second')
