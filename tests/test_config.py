from sql_agent_evals.config import Settings


def test_gold_sql_runs_as_the_agents_read_only_role(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = Settings(_env_file=None).database_url.get_secret_value()
    assert url.startswith("postgresql://agent_ro:")
