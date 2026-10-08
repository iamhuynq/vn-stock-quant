from fireant_crawler.config import load_settings
from fireant_crawler.dotenv import read_env_file


def test_reads_unquoted_bearer_value_with_space(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nFIREANT_TOKEN=Bearer abc.def.ghi\n\nexport RATE_LIMIT_RPS = '2'\nBROKEN LINE\n", encoding="utf-8")
    values = read_env_file(env)
    assert values == {"FIREANT_TOKEN": "Bearer abc.def.ghi", "RATE_LIMIT_RPS": "2"}
    assert load_settings(values).token == "abc.def.ghi"


def test_missing_file_returns_empty(tmp_path):
    assert read_env_file(tmp_path / "nope.env") == {}


def test_parsing_is_silent(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("FIREANT_TOKEN=Bearer secret-value-123456\n=novalue\n", encoding="utf-8")
    read_env_file(env)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
