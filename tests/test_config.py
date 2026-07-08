from app.config import get_config


def test_config_reads_default_port():
    config = get_config()
    assert config.web_port == 49175
    assert config.database_url
