import sys

import pytest

from venvdoctor.config import load_config


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib requires Python 3.11+")
def test_load_config_reads_cwd_file(tmp_path, monkeypatch):
    (tmp_path / ".venvdoctor.toml").write_text('top = 7\ndays_old = 30\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "definitely_not_home")

    config = load_config()
    assert config == {"top": 7, "days_old": 30}


def test_load_config_returns_empty_dict_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "definitely_not_home")

    assert load_config() == {}
